"""Client metadata and a fixed, tool-free diagnostic. No model names are pinned."""
import hashlib
import json
import math
import os
from pathlib import Path
import queue
import re
import subprocess
import threading
import time

from adoption_fs import hash_file
from capabilities import canonical, parse_json
from mission_backlog import require

EVENT_LIMIT = 1024 * 1024
OUTPUT_LIMIT = 8 * EVENT_LIMIT
CLIENTS = ('codex', 'claude')
# An executable/profile proof is independent of the changing account model catalog.
# Unknown builds keep discovery available and execution blocked until a new proof.
# Both native proofs remain open: Codex exposes view_image; Claude safe mode still
# accepts managed policy. An empty loopback tool catalog alone cannot certify it.
NATIVE_PROFILES = set()
API_KEYS = {'codex': ('OPENAI_API_KEY', 'CODEX_API_KEY'),
            'claude': ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')}
ROUTING_KEYS = ('OPENAI_BASE_URL', 'ANTHROPIC_BASE_URL', 'CLAUDE_CODE_USE_BEDROCK',
                'CLAUDE_CODE_USE_VERTEX', 'CLAUDE_CODE_USE_FOUNDRY')
CODEX_DISABLED = ('shell_tool', 'unified_exec', 'multi_agent', 'multi_agent_v2', 'code_mode',
                  'code_mode_host', 'apps', 'plugins', 'hooks', 'skill_search',
                  'skill_mcp_dependency_install', 'computer_use', 'browser_use',
                  'browser_use_external', 'in_app_browser', 'image_generation',
                  'workspace_dependencies', 'goals', 'tool_suggest')
CLAUDE_PROFILE = ['--safe-mode', '--tools', '', '--disallowedTools', 'mcp__*',
                  '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
                  '--disable-slash-commands', '--no-session-persistence', '--no-chrome',
                  '--settings', '{"disableAllHooks":true}']


def safe_name(value):
    return isinstance(value, str) and 0 < len(value) <= 256 and re.fullmatch(r'[A-Za-z0-9_.:/\[\]-]+', value)


def _exchange(executable, args, cwd, requests=None, *, merge_stderr=False):
    """Bounded local discovery. No user/model turn is ever sent here."""
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    process = subprocess.Popen([str(executable), *args], cwd=cwd, stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT if merge_stderr else subprocess.DEVNULL,
                               creationflags=flags, start_new_session=os.name != 'nt')
    inbox, stopped = queue.Queue(maxsize=32), threading.Event()

    def read():
        total = 0
        while not stopped.is_set():
            line = process.stdout.readline(EVENT_LIMIT + 1)
            total += len(line)
            value = line if len(line) <= EVENT_LIMIT and total <= OUTPUT_LIMIT else False
            while not stopped.is_set():
                try:
                    inbox.put(value, timeout=.1)
                    break
                except queue.Full:
                    continue
            if not line or value is False:
                return

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30

    def receive():
        try:
            value = inbox.get(timeout=max(.01, deadline - time.monotonic()))
        except queue.Empty:
            raise ValueError('client_discovery_timeout') from None
        require(value is not False, 'client_output_limit')
        return value

    try:
        if requests is None:
            process.stdin.close()
            chunks = []
            while True:
                line = receive()
                if not line:
                    break
                chunks.append(line)
            require(process.wait(timeout=3) == 0, 'client_discovery_failed')
            return b''.join(chunks).decode('utf-8', errors='strict')
        responses = []
        for request, expected in requests:
            process.stdin.write(canonical(request) + b'\n')
            process.stdin.flush()
            if expected is None:
                continue
            while True:
                line = receive()
                require(bool(line), 'client_discovery_failed')
                event = parse_json(line)
                require(isinstance(event, dict), 'client_protocol_error')
                if event.get('id') == expected or event.get('response', {}).get('request_id') == expected:
                    require('error' not in event, 'client_discovery_failed')
                    responses.append(event)
                    break
        return responses
    finally:
        stopped.set()
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=3)
        if not process.stdin.closed:
            process.stdin.close()
        thread.join(timeout=3)
        process.stdout.close()


def discover(executable, client, root):
    version_text = _exchange(executable, ['--version'], root)
    match = re.search(r'\b(\d+\.\d+\.\d+(?:-[\w.]+)?)\b', version_text)
    require(match is not None, 'unsupported_client')
    help_text = _exchange(executable, ['exec', '--help'] if client == 'codex' else ['--help'], root)
    if client == 'codex':
        controls = all(flag in help_text for flag in ('--json', '--ephemeral', '--sandbox', '--ignore-user-config'))
        pages, cursor = [], None
        for _ in range(10):
            response = _exchange(executable, ['app-server', '--stdio'], root, [
                ({'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'youngcrow', 'version': '1'}}}, 1),
                ({'method': 'initialized'}, None),
                ({'id': 2, 'method': 'model/list', 'params': {'limit': 100, 'includeHidden': False, 'cursor': cursor}}, 2)])[-1]
            result = response.get('result', {})
            require(isinstance(result.get('data'), list), 'client_protocol_error')
            pages.extend(result['data'])
            next_cursor = result.get('nextCursor')
            if next_cursor is None:
                break
            require(isinstance(next_cursor, str) and next_cursor != cursor, 'client_protocol_error')
            cursor = next_cursor
        else:
            raise ValueError('client_catalog_limit')
        models = pages
    else:
        controls = all(flag in help_text for flag in ('--safe-mode', '--tools', '--strict-mcp-config', '--effort'))
        result = _exchange(executable, ['--print', '--input-format', 'stream-json',
                           '--output-format', 'stream-json', '--verbose', *CLAUDE_PROFILE], root, [
            ({'type': 'control_request', 'request_id': 'init', 'request': {'subtype': 'initialize'}}, 'init')])[0]
        response = result.get('response', {})
        require(response.get('subtype') == 'success', 'client_discovery_failed')
        models = response.get('response', {}).get('models')
        require(isinstance(models, list), 'client_protocol_error')
    auth = 'unknown'
    try:
        raw = _exchange(executable, ['login', 'status'] if client == 'codex' else ['auth', 'status'], root, merge_stderr=client == 'codex')
        if client == 'codex':
            if 'logged in using chatgpt' in raw.lower():
                auth = 'authenticated'
            elif 'api key' in raw.lower():
                auth = 'api'
        else:
            status = parse_json(raw.encode())
            if status.get('loggedIn') is True:
                auth = 'authenticated' if status.get('authMethod') == 'claude.ai' else 'api' if status.get('authMethod') in ('api_key', 'api_key_helper') else 'unknown'
    except (ValueError, OSError, TypeError, AttributeError):
        pass
    return dict(version=match.group(1), models=models, controls=controls, auth_kind=auth)


def model_catalog(client, entries):
    require(isinstance(entries, list) and len(entries) <= 1000, 'client_catalog_limit')
    result = []
    for entry in entries:
        require(isinstance(entry, dict), 'client_protocol_error')
        name = entry.get('model') if client == 'codex' else entry.get('resolvedModel', entry.get('value'))
        alias = name if client == 'codex' else entry.get('value')
        require(safe_name(name) and safe_name(alias), 'client_protocol_error')
        efforts = ([v.get('reasoningEffort') for v in entry.get('supportedReasoningEfforts', [])]
                   if client == 'codex' else entry.get('supportedEffortLevels', []))
        require(isinstance(efforts, list) and all(safe_name(v) for v in efforts), 'client_protocol_error')
        default = entry.get('isDefault', False) if client == 'codex' else alias == 'default'
        require(type(default) is bool, 'client_protocol_error')
        suggested = entry.get('defaultReasoningEffort') if client == 'codex' else None
        result.append(dict(model=name, alias=alias, efforts=efforts,
                           default_effort=suggested if suggested in efforts else None, is_default=default))
    return result


def policy_snapshot(root, client):
    root = Path(root).resolve()
    paths = [root / p for p in ('AGENTS.md', 'CLAUDE.md', '.codex/config.toml', '.codex/hooks.json',
                                '.claude/settings.json', '.claude/settings.local.json', '.mcp.json')]
    try:
        home = Path.home()
    except RuntimeError:
        raise ValueError('unsupported_policy') from None
    codex_home = Path(os.environ.get('CODEX_HOME', home / '.codex'))
    claude_home = Path(os.environ.get('CLAUDE_CONFIG_DIR', home / '.claude'))
    paths += [codex_home / 'config.toml', codex_home / 'hooks.json', claude_home / 'settings.json']
    managed = ([Path(os.environ.get('ProgramData', 'C:/ProgramData')) / 'ClaudeCode/managed-settings.json',
                Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'ClaudeCode/managed-settings.json']
               if os.name == 'nt' else [Path('/etc/claude-code/managed-settings.json'),
                                        Path('/Library/Application Support/ClaudeCode/managed-settings.json')])
    managed += [Path('/etc/codex/requirements.toml'), codex_home / 'requirements.toml']
    values = {}
    for path in paths + managed:
        require(not path.is_symlink(), 'unsupported_policy')
        values[str(path)] = hash_file(path) if path.exists() else None
    return hashlib.sha256(canonical(values)).hexdigest(), ['managed_policy_unverified'] if any(p.exists() for p in managed) else []


def inspect_client(root: Path, client: str, executable: Path) -> dict:
    require(client in CLIENTS, 'invalid_client')
    executable = Path(executable).absolute()
    require(executable.is_file() and not executable.is_symlink(), 'invalid_executable')
    require(os.name != 'nt' or executable.suffix.lower() == '.exe', 'invalid_executable')
    before = hash_file(executable)
    digest, gaps = policy_snapshot(root, client)
    try:
        discovered = discover(executable, client, Path(root).resolve())
        models = model_catalog(client, discovered['models'])
    except (OSError, UnicodeError, KeyError, TypeError, subprocess.SubprocessError):
        raise ValueError('client_discovery_failed') from None
    require(hash_file(executable) == before and policy_snapshot(root, client)[0] == digest, 'stale_observation')
    if not discovered['controls']:
        gaps.append('unsupported_client_controls')
    if not discovered.get('profile_verified', False) and (os.name, client, discovered['version'], before) not in NATIVE_PROFILES:
        gaps.append('native_profile_unverified')
    return dict(client=client, version=discovered['version'], executable=str(executable),
                executable_sha256=before, root=str(Path(root).resolve()), protocol=client + '-json-v1',
                policy_digest=digest, connection_conflicts=[k for k in ROUTING_KEYS if os.environ.get(k)],
                gaps=gaps, models=models, catalog_source='native_client',
                latest_selection='client_recommended', model_compatibility='not_verified',
                auth_kind=discovered.get('auth_kind', 'unknown'))


def build_check(agent: dict, observation: dict, manifest: dict) -> dict:
    client = agent['client']
    require(client in CLIENTS and observation['client'] == client, 'invalid_client')
    require(not observation['gaps'], 'unsupported_policy')
    executable = Path(observation['executable'])
    require(hash_file(executable) == observation['executable_sha256'] and
            policy_snapshot(Path(observation['root']), client)[0] == observation['policy_digest'], 'stale_observation')
    require(not any(os.environ.get(k) for k in ROUTING_KEYS), 'connection_conflict')
    require(agent['connection'] in ('authenticated', 'api'), 'invalid_connection')
    if agent['connection'] == 'authenticated':
        require(not any(os.environ.get(k) for k in API_KEYS[client]), 'connection_conflict')
        require(observation['auth_kind'] == 'authenticated', 'connection_unverified')
    else:
        require(safe_name(agent.get('credential_env')), 'invalid_connection')
        require(manifest.get('api_budget_usd') is not None, 'api_budget_required')
    requested = agent['model']
    if requested == 'latest':
        choices = [m for m in observation['models'] if m['is_default']]
    else:
        choices = [m for m in observation['models'] if requested in (m['model'], m['alias'])]
    require(bool(choices), 'unsupported_combination')
    require(len({(m['model'], tuple(m['efforts'])) for m in choices}) == 1, 'ambiguous_model')
    selected = choices[0]
    effort = agent['effort']['native_value'] if agent['effort']['level'] == 'native' else agent['effort']['level']
    require(effort == 'client-default' or effort in selected['efforts'], 'unsupported_combination')
    require(not agent.get('capabilities'), 'unsupported_probe_capabilities')
    nonce = manifest['operation_id']
    prompt = ('Return only this JSON object, with the same probe_id. No tools or other actions: '
              + json.dumps({'probe_id': nonce}))
    if client == 'codex':
        args = ['exec', '--json', '--ephemeral', '--ignore-user-config', '--sandbox', 'read-only',
                '--skip-git-repo-check', '--color', 'never', '--model', selected['model'],
                '-c', 'approval_policy="never"', '-c', 'web_search="disabled"',
                '-c', 'mcp_servers={}', '-c', 'tools.view_image=false']
        if effort != 'client-default':
            args += ['-c', 'model_reasoning_effort=' + json.dumps(effort)]
        for feature in CODEX_DISABLED:
            args.extend(['--disable', feature])
        args.append('-')
    else:
        args = ['--print', '--output-format', 'stream-json', '--verbose', *CLAUDE_PROFILE,
                '--model', selected['model'], '--permission-mode', 'dontAsk']
        if effort != 'client-default':
            args += ['--effort', effort]
        if agent['connection'] == 'api':
            args += ['--max-budget-usd', manifest['api_budget_usd']]
    return dict(argv=[str(executable), *args], cwd=str(Path(observation['root']) / 'vault/local/operations/checks' / nonce),
                stdin=prompt.encode(), timeout_seconds=manifest['agent_seconds'], output_limit_bytes=OUTPUT_LIMIT,
                client=client, connection=agent['connection'], requested_model=requested,
                resolved_model=selected['model'], requested_effort=effort, policy_digest=observation['policy_digest'],
                executable_sha256=observation['executable_sha256'], credential_env=agent['credential_env'],
                expected_nonce=nonce, version=observation['version'],
                execution_gaps=(['api_budget_unenforceable'] if client == 'codex' else ['api_connection_unverified'])
                if agent['connection'] == 'api' else [])


def parse_events(data: bytes) -> list[dict]:
    require(isinstance(data, bytes) and len(data) <= OUTPUT_LIMIT, 'client_output_limit')
    events = []
    try:
        for line in data.splitlines():
            if not line.strip():
                continue
            require(len(line) <= EVENT_LIMIT, 'client_output_limit')
            event = parse_json(line)
            require(isinstance(event, dict) and isinstance(event.get('type'), str), 'client_protocol_error')
            events.append(event)
    except (ValueError, UnicodeError, RecursionError):
        raise ValueError('client_protocol_error') from None
    return events


def decode_result(client: str, events: list[dict], expected_nonce: str) -> dict:
    require(client in CLIENTS and isinstance(events, list), 'client_protocol_error')
    message, terminal, models = None, None, set()
    for event in events:
        require(isinstance(event, dict), 'client_protocol_error')
        kind = event.get('type')
        if client == 'codex':
            if kind in ('item.started', 'item.updated', 'item.completed'):
                item = event.get('item', {})
                require(item.get('type') in ('agent_message', 'reasoning'), 'unexpected_tool')
                if kind == 'item.completed' and item.get('type') == 'agent_message':
                    require(message is None, 'client_protocol_error')
                    message = item.get('text')
            elif kind == 'turn.completed':
                require(terminal is None, 'client_protocol_error')
                terminal = event
            else:
                require(kind in ('thread.started', 'turn.started'), 'client_protocol_error')
        else:
            if kind == 'system':
                require(event.get('subtype') == 'init' and not event.get('tools'), 'unexpected_tool')
                if event.get('model'):
                    models.add(event['model'])
            elif kind == 'assistant':
                payload = event.get('message', {})
                if payload.get('model'):
                    models.add(payload['model'])
                require(all(c.get('type') in ('text', 'thinking') for c in payload.get('content', [])), 'unexpected_tool')
            elif kind == 'result':
                require(terminal is None and event.get('subtype') == 'success' and event.get('is_error') is False,
                        'client_protocol_error')
                require(event.get('num_turns') == 1, 'unexpected_turns')
                terminal, message = event, event.get('result')
            else:
                raise ValueError('client_protocol_error')
    require(terminal is not None and terminal is events[-1] and isinstance(message, str), 'client_protocol_error')
    require(len(models) <= 1, 'model_mismatch')
    try:
        require(parse_json(message.encode()) == {'probe_id': expected_nonce}, 'invalid_probe_result')
    except (UnicodeError, RecursionError):
        raise ValueError('invalid_probe_result') from None
    require(isinstance(terminal.get('usage', {}), dict), 'client_protocol_error')
    usage = {k: v for k, v in terminal.get('usage', {}).items()
             if k in ('input_tokens', 'output_tokens', 'cached_input_tokens', 'cache_read_input_tokens')
             and type(v) is int and v >= 0}
    cost = terminal.get('total_cost_usd')
    require(cost is None or (type(cost) in (int, float) and math.isfinite(cost) and cost >= 0), 'client_protocol_error')
    return dict(state='succeeded', observed_model=next(iter(models), None), observed_effort=None,
                usage=usage, cost_usd=str(cost) if cost is not None else None, tools_observed=[])
