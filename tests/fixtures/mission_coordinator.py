"""Crash a real coordinator after the fixture produced its external marker."""
import json
import os
from pathlib import Path
import sys
import threading
import time
from unittest.mock import patch

repo = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(repo / 'scripts'), str(repo / 'tests')]
import mission_clients
import mission_runs
from test_mission_clients import catalog

root = Path(sys.argv[1])
manifest = json.loads((root / 'vault/local/crash-manifest.json').read_text())
marker = root / 'vault/local/operations/checks' / manifest['operation_id'] / 'dispatches.txt'
if len(sys.argv) > 2 and sys.argv[2] == 'before-effect':
    with patch.object(mission_clients, 'discover', return_value=dict(version='0.146.0', models=catalog('codex'), controls=True, auth_kind='authenticated', profile_verified=True)):
        observation = mission_clients.inspect_client(root, 'codex', Path(sys.executable))
        mission_runs.reserve_check(root, manifest, observation)
    os._exit(9)


def crash():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if marker.exists():
            os._exit(9)
        time.sleep(.02)


threading.Thread(target=crash, daemon=True).start()
original = mission_clients.build_check


def build(*args):
    return dict(original(*args), argv=[sys.executable, '-I', '-S', str(Path(__file__).with_name('mission_client.py')), 'after-effect'])


with patch.object(mission_clients, 'discover', return_value=dict(version='0.146.0', models=catalog('codex'), controls=True, auth_kind='authenticated', profile_verified=True)):
    with patch.object(mission_clients, 'build_check', side_effect=build):
        mission_runs.check_client(root, manifest, Path(sys.executable))
