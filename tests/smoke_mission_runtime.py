"""Installed-consumer diagnostic proof. Native model calls require a separate manifest."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import uuid

from smoke_mission_foundation import mission_smoke, check
from smoke_adoption import ROOT, run, write

INJECTION = '''import json,sys,os,threading,time
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,'scripts')
import missions,mission_clients,mission_runs,mission_process
assert Path(mission_runs.__file__).resolve().parent == Path.cwd() / 'scripts'
original=mission_clients.build_check
mode=sys.argv[3]
if mode == 'coordinator-crash':
    manifest=json.loads(Path(sys.argv[1]).read_text())
    marker=Path('vault/local/operations/checks') / manifest['operation_id'] / 'dispatches.txt'
    def crash():
        while not marker.exists():
            time.sleep(.02)
        os._exit(9)
    threading.Thread(target=crash,daemon=True).start()
    mode='after-effect'
def build(*args):
    plan=original(*args)
    return dict(plan,argv=[sys.executable,'-I','-S',sys.argv[2],mode])
metadata=dict(version='fixture-1',controls=True,auth_kind='authenticated',profile_verified=True,
              models=[dict(model='fixture-a',isDefault=True,defaultReasoningEffort='medium',
                           supportedReasoningEfforts=[dict(reasoningEffort='medium')])])
with patch.object(mission_clients,'discover',return_value=metadata):
    with patch.object(mission_clients,'build_check',side_effect=build):
        sys.exit(missions.main(['client','check','--manifest',sys.argv[1],'--executable',sys.executable,'--json']))
'''


def runtime_smoke(root, client):
    outcomes = []

    def exercise(project, case, env, mission_id):
        manifest = dict(schema_version=1, mission_id=mission_id, mission_revision=1, role='pm',
                        operation_id=str(uuid.uuid4()), authorization_ref='Authorized deterministic adoption smoke',
                        agent_seconds=60, max_runs=1, api_budget_usd=None, fixture_id='echo-v1')
        relative = 'vault/local/runtime-manifest.json'

        def invoke(mode='success', expected=0):
            write(project / relative, json.dumps(manifest).encode())
            return run([sys.executable, '-B', '-c', INJECTION, relative,
                        str(ROOT / 'tests/fixtures/mission_client.py'), mode], env=env, cwd=project, expected=expected)

        def check_client(mode='success', expected=0):
            return json.loads(invoke(mode, expected))

        first = check_client()
        repeated = check_client()
        check(first['id'] == repeated['id'] and repeated['state'] == 'succeeded', 'duplicate_check')
        marker = project / 'vault/local/operations/checks' / manifest['operation_id'] / 'dispatches.txt'
        check(marker.read_text() == '1\n', 'duplicate_dispatch')
        before = {p.relative_to(project).as_posix(): p.read_bytes() for p in (project / 'vault').rglob('*') if p.is_file()}
        history = json.loads(run([sys.executable, '-B', 'scripts/missions.py', 'client', 'runs', '--mission', mission_id, '--json'], env=env, cwd=project))
        after = {p.relative_to(project).as_posix(): p.read_bytes() for p in (project / 'vault').rglob('*') if p.is_file()}
        check(before == after and len(history['runs']) == 1, 'readonly_receipts_failed')
        manifest.update(operation_id=str(uuid.uuid4()), agent_seconds=5)
        timeout = check_client('child', expected=1)
        check(timeout['state'] == 'interrupted' and timeout['reason'] == 'timeout', 'timeout_not_enforced')
        manifest.update(operation_id=str(uuid.uuid4()), agent_seconds=60)
        invoke('coordinator-crash', expected=9)
        # Give native containment a bounded window to reap the crashed coordinator's child.
        import time
        for _ in range(20):
            crashed = check_client(expected=1)
            if crashed['state'] == 'uncertain':
                break
            time.sleep(.1)
        check(crashed['state'] == 'uncertain', 'crash_not_recovered')
        marker = project / 'vault/local/operations/checks' / manifest['operation_id'] / 'dispatches.txt'
        check(marker.read_text() == '1\n', 'crash_dispatched_twice')
        proof = 'vault/local/runtime-reconciliation.txt'
        write(project / proof, b'Fixture: owned tree terminated; only the expected nonce was emitted. Reviewed.')
        reference = dict(path=proof, sha256=hashlib.sha256((project / proof).read_bytes()).hexdigest())
        evidence = 'vault/local/runtime-evidence.json'
        write(project / evidence, json.dumps(dict(authorization_ref='Authorized deterministic fixture recovery',
                                                  termination=reference, external_effect=reference)).encode())
        recovered = json.loads(run([sys.executable, '-B', 'scripts/missions.py', 'client', 'reconcile',
                                    '--run', crashed['id'], '--evidence', evidence,
                                    '--expected-revision', str(crashed['revision']), '--operation-id', str(uuid.uuid4()),
                                    '--json'], env=env, cwd=project, expected=1))
        check(recovered['state'] == 'interrupted' and recovered['cost_usd'] is None, 'reconciliation_failed')
        status = json.loads(run([sys.executable, '-B', 'scripts/missions.py', '--json', 'status', mission_id], env=env, cwd=project))
        check(not status['runnable'] and status['check_available'], 'mission_execution_enabled')
        outcomes.append(dict(mode=case, diagnostic='succeeded', replay='same_run', dispatches=1,
                             read_only=True, timeout='interrupted', crash='uncertain', reconciliation='interrupted',
                             runtime_available=False))

    return dict(mission_smoke(root, client, extra_check=exercise), diagnostics=outcomes)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--client', choices=('claude', 'codex', 'both'), default='both')
    parser.add_argument('--native-manifest')
    parser.add_argument('--executable', type=Path)
    args = parser.parse_args()
    try:
        if args.native_manifest:
            if args.executable is None:
                raise ValueError('explicit_executable_required')
            # The caller supplies an already prepared consumer and explicit operation manifest.
            return subprocess.run([sys.executable, '-B', str(args.root.resolve() / 'scripts/missions.py'),
                                   '--root', str(args.root), 'client', 'check', '--manifest', args.native_manifest,
                                   '--executable', str(args.executable), '--json'], check=False).returncode
        check(args.executable is None, 'native_manifest_required')
        print(json.dumps(runtime_smoke(args.root, args.client), ensure_ascii=True))
        return 0
    except (ValueError, OSError, subprocess.SubprocessError, KeyError):
        print(json.dumps(dict(state='failed', code='mission_runtime_smoke_failed')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
