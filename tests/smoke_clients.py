"""Optional real-client discovery checks. No paid model calls or MCP connections.

The Codex agent check captures one request on a loopback-only model fixture.

python tests/smoke_clients.py --codex /path/to/codex --claude /path/to/claude
On Windows pass the actual .exe files, not npm's .ps1/.cmd launchers.
"""
import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import queue
import subprocess
import threading
import time

from test_setup import SetupTests, write


def check_codex(executable, project, env):
    process = subprocess.Popen([executable, 'app-server', '--stdio'], cwd=project, env=env,
                               stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
    messages = queue.Queue()

    def read_messages():
        for line in process.stdout:
            messages.put(json.loads(line))

    reader = threading.Thread(target=read_messages, daemon=True)
    reader.start()

    def request(number, method, params):
        process.stdin.write(json.dumps({'id': number, 'method': method, 'params': params}) + '\n')
        process.stdin.flush()
        deadline = time.monotonic() + 20
        while True:
            response = messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if response.get('id') == number:
                assert 'error' not in response, response
                return response['result']

    try:
        request(1, 'initialize', {'clientInfo': {'name': 'youngcrow-smoke', 'version': '1.0'}})
        process.stdin.write('{"method":"initialized"}\n')
        process.stdin.flush()
        config = request(4, 'config/read', {'cwd': str(project), 'includeLayers': True})
        servers = config['config'].get('mcp_servers', {})
        assert set(servers) == {'n8n', 'cloudflare-api'}, config
        assert all(not s['enabled'] for s in servers.values())
        print('Codex: project MCP configuration recognized; example servers disabled.')
        skills = request(2, 'skills/list', {'cwds': [str(project)], 'forceReload': True})
        found = {s['name'] for entry in skills['data'] for s in entry['skills']}
        assert {'humanizer', 'humanizer-ptbr', 'integrate-from-docs', 'personalizer', 'ingest-source', 'retrieve-memory', 'govern-capabilities',
                'yc-personalizer', 'yc-config', 'yc-missao', 'yc-status'} <= found, found
        assert not any(entry['errors'] for entry in skills['data']), skills
        print('Codex: humanizer, humanizer-ptbr, integrate-from-docs, personalizer, ingest-source, retrieve-memory and govern-capabilities discovered by the real skill loader.')
        hooks = request(3, 'hooks/list', {'cwds': [str(project)]})
        assert not any(entry['errors'] for entry in hooks['data']), hooks
        found_hooks = [h for entry in hooks['data'] for h in entry['hooks']]
        assert {h['eventName'] for h in found_hooks} == {'postToolUse', 'stop', 'userPromptSubmit'}, hooks
        print('Codex: project UserPromptSubmit, PostToolUse and Stop hooks discovered; execution still requires trust.')
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        reader.join(timeout=2)
        process.stdin.close()
        process.stdout.close()


def check_claude_discovery(executable, project, env):
    # SDK initialization loads local metadata without sending a user/model turn.
    process = subprocess.Popen(
        [executable, '--print', '--input-format', 'stream-json', '--output-format', 'stream-json',
         '--verbose', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}'],
        cwd=project, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, encoding='utf-8')
    messages = queue.Queue()

    def read_messages():
        for line in process.stdout:
            messages.put(json.loads(line))

    reader = threading.Thread(target=read_messages, daemon=True)
    reader.start()
    try:
        process.stdin.write(json.dumps({'type': 'control_request', 'request_id': 'init',
                                        'request': {'subtype': 'initialize'}}) + '\n')
        process.stdin.flush()
        deadline = time.monotonic() + 25
        while True:
            message = messages.get(timeout=max(0.01, deadline - time.monotonic()))
            if message.get('type') == 'control_response':
                response = message['response']
                assert response.get('subtype') == 'success', response
                data = response['response']
                assert any(c['name'] == 'integrate-from-docs' for c in data['commands']), data.keys()
                assert any(c['name'] == 'personalizer' for c in data['commands']), data.keys()
                assert any(c['name'] == 'ingest-source' for c in data['commands']), data.keys()
                assert any(c['name'] == 'retrieve-memory' for c in data['commands']), data.keys()
                assert any(c['name'] == 'govern-capabilities' for c in data['commands']), data.keys()
                assert {'yc-personalizer', 'yc-config', 'yc-missao', 'yc-status'} <= {c['name'] for c in data['commands']}
                assert any(a['name'] == 'integration-specialist' for a in data['agents']), data.keys()
                print('Claude: govern-capabilities, retrieve-memory, ingest-source, personalizer, integrate-from-docs and integration-specialist discovered by SDK initialization; no model turn.')
                break
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        reader.join(timeout=2)
        process.stdin.close()
        process.stdout.close()


def check_codex_agent(executable, project, env):
    """Capture one request to a loopback-only model fixture; no paid model call."""
    requests = queue.Queue()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.put(self.rfile.read(int(self.headers['Content-Length'])).decode('utf-8'))
            self.send_response(400)
            self.end_headers()

    server = HTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    process = subprocess.Popen(
        [executable, 'exec', '--json', '--skip-git-repo-check', '--sandbox', 'read-only',
         '-c', 'model="local-fixture"', '-c', 'model_provider="fixture"',
         '-c', 'model_providers.fixture.name="Local fixture"',
         '-c', f'model_providers.fixture.base_url="http://127.0.0.1:{server.server_port}/v1"',
         '-c', 'model_providers.fixture.wire_api="responses"',
         '-c', 'model_providers.fixture.requires_openai_auth=false',
         'List the custom agent names; do not execute tools.'],
        cwd=project, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        body = json.loads(requests.get(timeout=30))
        assert 'integration-specialist' in json.dumps(body.get('tools', [])), 'Specialist missing from native tool catalog'
        print('Codex: integration-specialist exposed in native agent tool catalog (loopback fixture, no paid model).')
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--codex', required=True)
    parser.add_argument('--claude', required=True)
    args = parser.parse_args()
    test = SetupTests()
    test.setUp()
    try:
        result = test.run_setup('--client', 'both', '--no-plugins', timeout=180)
        assert result.returncode == 0, result.stderr
        test.git('init', '-q', str(test.target))
        env = test.child_env.copy()
        # Native clients must never discover the real user's home or credentials.
        env.update(HOME=str(test.home), USERPROFILE=str(test.home),
                   CODEX_HOME=str(test.home / '.codex'), CLAUDE_CONFIG_DIR=str(test.home / '.claude'),
                   CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1')
        if os.name == 'nt':
            env.update(APPDATA=str(test.home / 'AppData/Roaming'), LOCALAPPDATA=str(test.home / 'AppData/Local'))
        write(test.home / '.codex/config.toml',
              '[projects.' + json.dumps(os.path.normcase(str(test.target))) + ']\ntrust_level = "trusted"\n')
        check_codex(str(Path(args.codex).resolve()), test.target, env)
        result = subprocess.run([str(Path(args.claude).resolve()), 'mcp', 'get', 'n8n'], cwd=test.target,
                                env=env, capture_output=True, encoding='utf-8', check=True, timeout=25)
        assert 'n8n.SEU-DOMINIO.example' in result.stdout, result.stdout
        assert 'Pending approval' in result.stdout, result.stdout
        print('Claude: project MCP recognized and awaiting approval; no connection attempted.')
        check_claude_discovery(str(Path(args.claude).resolve()), test.target, env)
        check_codex_agent(str(Path(args.codex).resolve()), test.target, env)
    finally:
        test.doCleanups()


if __name__ == '__main__':
    main()
