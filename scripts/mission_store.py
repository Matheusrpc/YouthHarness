"""Local transactional history. Reading never initializes or repairs storage."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import uuid

from capabilities import canonical, text
from document_store import safe_path, prepare_storage, verify_private_storage
from mission_backlog import identity, project_id, require

DB_PATH = 'vault/local/operations/state.sqlite3'
RUNTIME_SCHEMA = 2
PREFIXES = dict(epic='E', feature='F', pbi='P', mission='M')
SCHEMA = (
    'CREATE TABLE metadata (schema_version INTEGER NOT NULL, project_id TEXT NOT NULL)',
    'CREATE TABLE records (id TEXT PRIMARY KEY, kind TEXT NOT NULL, code TEXT UNIQUE NOT NULL, revision INTEGER NOT NULL, snapshot TEXT NOT NULL)',
    'CREATE TABLE events (seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT UNIQUE NOT NULL, operation_id TEXT UNIQUE NOT NULL, request_hash TEXT NOT NULL, record_id TEXT NOT NULL REFERENCES records(id), actor TEXT NOT NULL, created_at TEXT NOT NULL, old_revision INTEGER NOT NULL, new_revision INTEGER NOT NULL, snapshot TEXT NOT NULL, projection_state TEXT NOT NULL)',
    'CREATE TABLE projections (path TEXT PRIMARY KEY, sha256 TEXT NOT NULL, sequence INTEGER NOT NULL REFERENCES events(seq))',
)


def preflight(root):
    project = project_id(root)
    for suffix in ('', '-journal', '-wal', '-shm'):
        safe_path(root, DB_PATH + suffix)
    for path in ('vault/local/index.md', 'vault/local/operations/index.md',
                 'vault/local/operations/items/index.md', 'vault/local/operations/events/index.md',
                 'vault/local/missions/index.md'):
        safe_path(root, path)
    verify_private_storage(root)
    return project


def validate_database(conn, project):
    metadata = conn.execute('SELECT schema_version, project_id FROM metadata').fetchall()
    require(metadata in ([(1, project)], [(2, project)]), 'invalid_store')
    conn.execute('SELECT id,kind,code,revision,snapshot FROM records LIMIT 0')
    conn.execute('SELECT seq,id,operation_id,request_hash,record_id,actor,created_at,old_revision,new_revision,snapshot,projection_state FROM events LIMIT 0')
    conn.execute('SELECT path,sha256,sequence FROM projections LIMIT 0')
    if metadata[0][0] == 2:
        conn.execute('SELECT id,mission_id,mission_revision,operation_id,request_hash,revision,state,snapshot FROM agent_runs LIMIT 0')
        conn.execute('SELECT seq,id,run_id,operation_id,request_hash,old_revision,new_revision,created_at,kind,payload,projection_state FROM agent_run_events LIMIT 0')
        conn.execute('SELECT path,sha256,sequence FROM agent_run_projections LIMIT 0')


@contextmanager
def reader(root, *, project=None):
    path = safe_path(root, DB_PATH)
    if not path.exists() or path.stat().st_size == 0:
        yield None
        return
    project = preflight(root) if project is None else project
    conn = None
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
        conn.execute('PRAGMA trusted_schema=OFF')
        validate_database(conn, project)
        yield conn
    except sqlite3.Error:
        raise ValueError('invalid_store') from None
    finally:
        if conn is not None:
            conn.close()


@contextmanager
def transaction(root: Path):
    project = preflight(root)
    path = safe_path(root, DB_PATH)
    if not path.exists() or path.stat().st_size == 0:
        prepare_storage(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = None
    try:
        conn = sqlite3.connect(path, timeout=3, isolation_level=None)
        conn.execute('PRAGMA trusted_schema=OFF')
        # A writable connection lets SQLite roll back a hot journal before reading its schema.
        # Validate existing tables before changing journal mode or any application data.
        if conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            validate_database(conn, project)
        conn.execute('PRAGMA foreign_keys=ON')
        require(conn.execute('PRAGMA journal_mode=DELETE').fetchone()[0] == 'delete', 'invalid_store')
        conn.execute('BEGIN IMMEDIATE')
        tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        if not tables:
            for statement in SCHEMA:
                conn.execute(statement)
            conn.execute('INSERT INTO metadata VALUES (1,?)', (project,))
        validate_database(conn, project)
        yield conn
        conn.commit()
    except sqlite3.OperationalError as error:
        if conn is not None:
            conn.rollback()
        raise ValueError('store_busy' if 'locked' in str(error) else 'invalid_store') from None
    except sqlite3.Error:
        if conn is not None:
            conn.rollback()
        raise ValueError('invalid_store') from None
    except BaseException:
        if conn is not None:
            conn.rollback()
        raise
    finally:
        if conn is not None:
            conn.close()


def actor_valid(actor):
    require(isinstance(actor, dict) and set(actor) == {'id', 'role'}, 'invalid_actor')
    require(text(actor['id'], 200) and actor['id'].strip() and actor['role'] in ('pm', 'tech_lead'), 'invalid_actor')


def request_hash(request, actor, expected_revision):
    identity(request['operation_id'])
    actor_valid(actor)
    require(type(expected_revision) is int and expected_revision >= 0, 'invalid_revision')
    return hashlib.sha256(canonical(dict(request=request, actor=actor, expected_revision=expected_revision))).hexdigest()


def event_dict(row):
    keys = ('sequence', 'event_id', 'operation_id', 'request_hash', 'record_id', 'actor',
            'created_at', 'old_revision', 'revision', 'record', 'projection_state')
    event = dict(zip(keys, row))
    event['actor'] = json.loads(event['actor'])
    event['record'] = json.loads(event['record'])
    return event


def receipt(conn, event):
    return dict(schema_version=1, project_id=conn.execute('SELECT project_id FROM metadata').fetchone()[0],
                operation_id=event['operation_id'], record_id=event['record_id'], code=event['record']['code'],
                revision=event['revision'], event_id=event['event_id'], sequence=event['sequence'],
                created_at=event['created_at'], projection_state=event['projection_state'])


def find_operation(conn, operation_id, digest):
    row = conn.execute('SELECT * FROM events WHERE operation_id=?', (operation_id,)).fetchone()
    if row is None:
        return None
    event = event_dict(row)
    require(event['request_hash'] == digest, 'operation_conflict')
    return receipt(conn, event)


def replay(root, operation_id, digest):
    with reader(root) as conn:
        return find_operation(conn, operation_id, digest) if conn is not None else None


def record_dict(row):
    return dict(id=row[0], kind=row[1], code=row[2], revision=row[3], snapshot=json.loads(row[4]))


def get_record(root: Path, identifier: str):
    with reader(root) as conn:
        row = conn.execute('SELECT * FROM records WHERE id=? OR code=?', (identifier, identifier)).fetchone() if conn else None
        return record_dict(row) if row else None


def list_records(root: Path, kind: str | None):
    with reader(root) as conn:
        return [record_dict(row) for row in conn.execute('SELECT * FROM records WHERE ? IS NULL OR kind=? ORDER BY code', (kind, kind))] if conn else []


def events(root, record_id):
    with reader(root) as conn:
        return [event_dict(row) for row in conn.execute('SELECT * FROM events WHERE record_id=? ORDER BY seq', (record_id,))] if conn else []


def commit_record(conn, *, record, expected_revision, operation_id, actor, now):
    identity(record['id'])
    require(record['kind'] in PREFIXES, 'invalid_record')
    digest = request_hash(dict(record['_request'], operation_id=operation_id), actor, expected_revision)
    existing_receipt = find_operation(conn, operation_id, digest)
    if existing_receipt:
        return existing_receipt
    existing = conn.execute('SELECT * FROM records WHERE id=?', (record['id'],)).fetchone()
    require((existing[3] if existing else 0) == expected_revision, 'revision_conflict')
    require(not existing or existing[1] == record['kind'], 'identity_conflict')
    if existing:
        code = existing[2]
    else:
        count = conn.execute('SELECT COUNT(*) FROM records WHERE kind=?', (record['kind'],)).fetchone()[0]
        code = f"{PREFIXES[record['kind']]}{count + 1:03}"
    saved = dict(id=record['id'], kind=record['kind'], code=code, revision=expected_revision + 1, snapshot=record['snapshot'])
    conn.execute('INSERT INTO records VALUES (?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,snapshot=excluded.snapshot',
                 (saved['id'], saved['kind'], code, saved['revision'], canonical(saved['snapshot']).decode()))
    conn.execute('INSERT INTO events(id,operation_id,request_hash,record_id,actor,created_at,old_revision,new_revision,snapshot,projection_state) VALUES(?,?,?,?,?,?,?,?,?,?)',
                 (str(uuid.uuid4()), operation_id, digest, saved['id'], canonical(actor).decode(), now, expected_revision, saved['revision'], canonical(saved).decode(), 'pending'))
    return find_operation(conn, operation_id, digest)
