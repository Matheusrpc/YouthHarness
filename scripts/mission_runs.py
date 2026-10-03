"""Durable, single-dispatch client diagnostics. This is not a mission worker."""
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import uuid

from capabilities import canonical, read_inputs, text
from document_store import safe_path
from mission_backlog import identity, require
from mission_config import config_digest
import mission_clients as clients
import mission_process as processes
import mission_store as store

UNRESOLVED = ('reserved', 'running', 'uncertain')
TERMINAL = ('succeeded', 'failed', 'interrupted')
MANIFEST = {'schema_version', 'mission_id', 'mission_revision', 'role', 'operation_id',
            'authorization_ref', 'agent_seconds', 'max_runs', 'api_budget_usd', 'fixture_id'}
SCHEMA = (
    'CREATE TABLE agent_runs (id TEXT PRIMARY KEY, mission_id TEXT NOT NULL REFERENCES records(id), mission_revision INTEGER NOT NULL, operation_id TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL, revision INTEGER NOT NULL, state TEXT NOT NULL, snapshot TEXT NOT NULL)',
    'CREATE TABLE agent_run_events (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, run_id TEXT NOT NULL REFERENCES agent_runs(id), operation_id TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL, old_revision INTEGER NOT NULL, new_revision INTEGER NOT NULL, created_at TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, projection_state TEXT NOT NULL)',
    'CREATE TABLE agent_run_projections (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, sequence INTEGER NOT NULL REFERENCES agent_run_events(seq))',
)


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec='microseconds')


def migrate(conn):
    if conn.execute('SELECT schema_version FROM metadata').fetchone()[0] == 1:
        for statement in SCHEMA:
            conn.execute(statement)
        conn.execute('UPDATE metadata SET schema_version=2')


def has_runs(conn):
    return conn is not None and conn.execute('SELECT schema_version FROM metadata').fetchone()[0] == 2


def list_runs(root: Path, mission_id: str) -> list[dict]:
    with store.reader(root) as conn:
        if not has_runs(conn):
            return []
        row = conn.execute('SELECT id FROM records WHERE kind=? AND (id=? OR code=?)', ('mission', mission_id, mission_id)).fetchone()
        return [json.loads(r[0]) for r in conn.execute('SELECT snapshot FROM agent_runs WHERE mission_id=? ORDER BY rowid', (row[0],))] if row else []


def find_run(conn, run_id):
    row = conn.execute('SELECT snapshot FROM agent_runs WHERE id=?', (run_id,)).fetchone()
    require(row is not None, 'unknown_run')
    return json.loads(row[0])


def manifest_valid(manifest):
    require(isinstance(manifest, dict) and set(manifest) == MANIFEST, 'invalid_manifest')
    require(type(manifest['schema_version']) is int and manifest['schema_version'] == 1, 'invalid_manifest')
    for key in ('mission_id', 'operation_id'):
        identity(manifest[key])
    for key in ('mission_revision', 'agent_seconds', 'max_runs'):
        require(type(manifest[key]) is int and manifest[key] > 0, 'invalid_manifest')
    require(manifest['max_runs'] == 1 and manifest['fixture_id'] == 'echo-v1', 'invalid_manifest')
    require(text(manifest['authorization_ref'], 1000) and manifest['authorization_ref'].strip(), 'invalid_manifest')
    require(isinstance(manifest['role'], str), 'invalid_manifest')
    budget = manifest['api_budget_usd']
    if budget is not None:
        import re
        require(isinstance(budget, str) and len(budget) <= 64 and re.fullmatch(r'\d+(?:\.\d+)?', budget)
                and Decimal(budget) > 0, 'invalid_manifest')


def mission_agent(root, manifest):
    import missions
    status = missions.mission_status(root, manifest['mission_id'])
    require(status.get('revision') == manifest['mission_revision'], 'revision_conflict')
    require(status['state'] == 'prepared' and not status['stale_inputs'], 'mission_not_ready')
    config = status['snapshot']['config']
    require(manifest['role'] in config['agents'], 'invalid_manifest')
    require(manifest['agent_seconds'] <= config['limits']['agent_seconds'], 'limit_exceeded')
    if manifest['api_budget_usd'] is not None:
        require(config['limits']['api_budget_usd'] is not None and
                Decimal(manifest['api_budget_usd']) <= Decimal(config['limits']['api_budget_usd']), 'limit_exceeded')
    return config['agents'][manifest['role']], config


def digest_manifest(manifest):
    return hashlib.sha256(canonical(manifest)).hexdigest()


def existing(root, manifest):
    manifest_valid(manifest)
    with store.reader(root) as conn:
        if not has_runs(conn):
            return None
        row = conn.execute('SELECT request_hash,snapshot FROM agent_runs WHERE operation_id=?', (manifest['operation_id'],)).fetchone()
        if row:
            require(row[0] == digest_manifest(manifest), 'operation_conflict')
            return json.loads(row[1])


def save_event(conn, run, event, revision, operation_id):
    stamp = now()
    digest = hashlib.sha256(canonical(dict(run_id=run['id'], event=event, revision=revision))).hexdigest()
    run.update(revision=revision + 1, updated_at=stamp)
    conn.execute('UPDATE agent_runs SET revision=?,state=?,snapshot=? WHERE id=?',
                 (run['revision'], run['state'], canonical(run).decode(), run['id']))
    conn.execute('INSERT INTO agent_run_events(id,run_id,operation_id,request_hash,old_revision,new_revision,created_at,kind,payload,projection_state) VALUES(?,?,?,?,?,?,?,?,?,?)',
                 (str(uuid.uuid4()), run['id'], operation_id, digest, revision, run['revision'], stamp, event['kind'], canonical(event).decode(), 'pending'))
    return run


def reserve_check(root: Path, manifest: dict, observation: dict) -> dict:
    repeated = existing(root, manifest)
    if repeated:
        return repeated
    agent, config = mission_agent(root, manifest)
    plan = clients.build_check(agent, observation, manifest)
    require(not plan['execution_gaps'], 'unsupported_policy')
    # The model's diagnostic profile is separate from process-tree containment.
    with store.transaction(root) as conn:
        migrate(conn)
        row = conn.execute('SELECT request_hash,snapshot FROM agent_runs WHERE operation_id=?', (manifest['operation_id'],)).fetchone()
        if row:
            require(row[0] == digest_manifest(manifest), 'operation_conflict')
            return json.loads(row[1])
        require(not conn.execute("SELECT 1 FROM agent_runs WHERE state IN ('reserved','running','uncertain') LIMIT 1").fetchone(), 'unresolved_run')
        current = conn.execute('SELECT revision FROM records WHERE id=?', (manifest['mission_id'],)).fetchone()
        require(current and current[0] == manifest['mission_revision'], 'revision_conflict')
        previous = [json.loads(r[0]) for r in conn.execute('SELECT snapshot FROM agent_runs WHERE mission_id=?', (manifest['mission_id'],))]
        require(len(previous) < config['limits']['max_agent_runs'], 'limit_exceeded')
        require(sum(r['reserved_seconds'] for r in previous) + manifest['agent_seconds'] <= config['limits']['mission_active_seconds'], 'limit_exceeded')
        if manifest['api_budget_usd'] is not None:
            used = sum(Decimal(r['manifest']['api_budget_usd'] or '0') for r in previous)
            require(used + Decimal(manifest['api_budget_usd']) <= Decimal(config['limits']['api_budget_usd']), 'limit_exceeded')
        run = dict(schema_version=1, id=str(uuid.uuid4()), mission_id=manifest['mission_id'],
                   mission_revision=manifest['mission_revision'], operation_id=manifest['operation_id'],
                   manifest=manifest, purpose='client_check', state='reserved', revision=0,
                   created_at=now(), started_at=None, ended_at=None, owner=None, reason=None,
                   coordinator_pid=os.getpid(),
                   config_digest=config_digest(config),
                   reserved_seconds=manifest['agent_seconds'], attempts=1, cost_usd=None, usage={},
                   observed_model=None, observed_effort=None, elapsed_seconds=None, exit_code=None,
                   capabilities_requested=agent['capabilities'], tools_observed=[],
                   **{k: plan[k] for k in ('client', 'connection', 'version', 'requested_model', 'resolved_model',
                                          'requested_effort', 'policy_digest', 'executable_sha256')})
        conn.execute('INSERT INTO agent_runs VALUES(?,?,?,?,?,?,?,?)',
                     (run['id'], run['mission_id'], run['mission_revision'], run['operation_id'], digest_manifest(manifest), 0, 'reserved', canonical(run).decode()))
        return save_event(conn, run, dict(kind='reserved'), 0, manifest['operation_id'])


def transition_run(root: Path, run_id: str, event: dict, expected_revision: int, operation_id: str) -> dict:
    identity(run_id)
    identity(operation_id)
    require(type(expected_revision) is int and expected_revision > 0, 'invalid_revision')
    require(isinstance(event, dict) and event.get('kind') in ('started', 'finished', 'uncertain', 'reconciled'), 'invalid_transition')
    digest = hashlib.sha256(canonical(dict(run_id=run_id, event=event, revision=expected_revision))).hexdigest()
    with store.transaction(root) as conn:
        require(has_runs(conn), 'unknown_run')
        old = conn.execute('SELECT request_hash FROM agent_run_events WHERE operation_id=?', (operation_id,)).fetchone()
        if old:
            require(old[0] == digest, 'operation_conflict')
            return find_run(conn, run_id)
        run = find_run(conn, run_id)
        require(run['revision'] == expected_revision, 'revision_conflict')
        require(run['state'] in UNRESOLVED, 'invalid_transition')
        if event['kind'] == 'started':
            require(run['state'] == 'reserved' and set(event) == {'kind', 'owner'}, 'invalid_transition')
            require(isinstance(event['owner'], dict) and set(event['owner']) == {'kind', 'name', 'pid'}, 'invalid_transition')
            run.update(state='running', owner=event['owner'], started_at=now())
        elif event['kind'] == 'uncertain':
            require(set(event) == {'kind'}, 'invalid_transition')
            run.update(state='uncertain', reason='reconciliation_required')
        elif event['kind'] == 'reconciled':
            require(set(event) == {'kind', 'evidence'}, 'invalid_transition')
            run.update(state='interrupted', reason='operator_reconciled', ended_at=now(), evidence=event['evidence'])
        else:
            allowed = {'kind', 'state', 'reason', 'exit_code', 'elapsed_seconds', 'observed_model',
                       'observed_effort', 'usage', 'cost_usd', 'tools_observed'}
            require(set(event) <= allowed and event.get('state') in (*TERMINAL, 'uncertain'), 'invalid_transition')
            require(event.get('reason') in ('completed', 'spawn_failed', 'timeout', 'cancelled', 'output_limit',
                                            'protocol_failed', 'tree_not_reaped', 'preflight_changed'), 'invalid_transition')
            run.update({k: v for k, v in event.items() if k != 'kind'})
            run['ended_at'] = now() if run['state'] in TERMINAL else None
        return save_event(conn, run, event, expected_revision, operation_id)


def project(root, run):
    from mission_vault import project_run
    try:
        projection = project_run(root, run['id'])
        return dict(run, projection_state=projection['state'], paths=projection['paths'])
    except (OSError, ValueError):
        return dict(run, projection_state='pending', paths=[])


def check_client(root: Path, manifest: dict, executable: Path) -> dict:
    repeated = existing(root, manifest)
    if repeated:
        if repeated['state'] == 'reserved' or (repeated['state'] == 'running' and processes.owner_gone(repeated['owner'])):
            repeated = transition_run(root, repeated['id'], dict(kind='uncertain'), repeated['revision'], str(uuid.uuid4()))
        return project(root, repeated)
    agent, _ = mission_agent(root, manifest)
    observation = clients.inspect_client(root, agent['client'], executable)
    run = reserve_check(root, manifest, observation)
    # Another coordinator may have won the same reservation; revision alone is insufficient.
    # Claim is a CAS transition, before any client can start.
    plan = clients.build_check(agent, observation, manifest)
    folder = safe_path(root, str(Path(plan['cwd']).relative_to(root)).replace('\\', '/'))
    folder.mkdir(parents=True, exist_ok=True)

    claimed = False

    def started(owner):
        nonlocal run, claimed
        mission_agent(root, manifest)
        clients.build_check(agent, observation, manifest)
        run = transition_run(root, run['id'], dict(kind='started', owner=owner), run['revision'], str(uuid.uuid4()))
        claimed = True

    try:
        result = processes.supervise(plan, on_started=started, stop_requested=lambda: False)
    except (OSError, ValueError):
        # A failed callback cannot release the bootstrap; unknown errors stay recoverable.
        with store.reader(root) as conn:
            run = find_run(conn, run['id'])
        if run['state'] not in TERMINAL and (claimed or run['state'] == 'reserved'):
            run = transition_run(root, run['id'], dict(kind='uncertain'), run['revision'], str(uuid.uuid4()))
        return project(root, run)
    event = dict(kind='finished', state='failed', reason=result['reason'], exit_code=result['exit_code'],
                 elapsed_seconds=result['elapsed_seconds'])
    if result['reason'] == 'completed' and result['exit_code'] != 0:
        event['reason'] = 'protocol_failed'
    if not result['tree_reaped']:
        event.update(state='uncertain', reason='tree_not_reaped')
    elif result['reason'] in ('timeout', 'cancelled'):
        event['state'] = 'interrupted'
    elif result['reason'] == 'completed' and result['exit_code'] == 0:
        try:
            decoded = clients.decode_result(agent['client'], clients.parse_events(result['stdout']), manifest['operation_id'])
            require(decoded['observed_model'] in (None, plan['resolved_model']), 'model_mismatch')
            event.update(decoded)
        except (ValueError, TypeError, KeyError, AttributeError):
            event.update(reason='protocol_failed')
    run = transition_run(root, run['id'], event, run['revision'], str(uuid.uuid4()))
    return project(root, run)


def reconcile_check(root: Path, run_id: str, evidence: dict, expected_revision: int, operation_id: str) -> dict:
    require(isinstance(evidence, dict) and set(evidence) == {'authorization_ref', 'termination', 'external_effect'}, 'insufficient_evidence')
    require(text(evidence['authorization_ref'], 1000) and evidence['authorization_ref'].strip(), 'insufficient_evidence')
    # Explicit operator-reviewed files, bound to exact bytes. Never execute their contents.
    for key in ('termination', 'external_effect'):
        ref = evidence[key]
        require(isinstance(ref, dict) and set(ref) == {'path', 'sha256'}, 'insufficient_evidence')
        require(hashlib.sha256(read_inputs(root, [ref['path']])[ref['path']]).hexdigest() == ref['sha256'], 'insufficient_evidence')
    with store.reader(root) as conn:
        require(has_runs(conn), 'unknown_run')
        run = find_run(conn, run_id)
    # Active or unidentifiable ownership remains blocked; no kill based on user-provided PID.
    require(processes.owner_gone(run['owner']) or
            (run['owner'] is None and processes.process_missing(run.get('coordinator_pid'))), 'insufficient_evidence')
    return project(root, transition_run(root, run_id, dict(kind='reconciled', evidence=evidence), expected_revision, operation_id))
