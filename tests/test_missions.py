import copy
import importlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import unittest
import uuid
from contextlib import closing, redirect_stdout
from unittest.mock import patch

from mission_fixtures import MissionCase
from mission_config import load_config, effective_config, config_digest

ACTOR = dict(id='fixture-pm', role='pm')
TL = dict(id='fixture-tl', role='tech_lead')
DB = 'vault/local/operations/state.sqlite3'


class MissionTests(MissionCase):
    def test_client_runs_is_readonly_on_fresh_project(self):
        before = self.snapshot()
        output = io.StringIO()
        with redirect_stdout(output):
            code = self.m.main(['--root', str(self.root), '--json', 'client', 'runs', '--mission', 'M001'])
        self.assertEqual(code, 0, output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['runs'], [])
        self.assertEqual(before, self.snapshot())

    def test_client_check_requires_manifest_and_sanitizes_errors(self):
        import mission_runs
        output = io.StringIO()
        with redirect_stdout(output):
            code = self.m.main(['--root', str(self.root), 'client', 'check', '--executable', sys.executable])
        self.assertNotEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())['error'], 'invalid_arguments')
        manifest = self.root / 'vault/local/probe.json'
        manifest.write_text('{}')
        output = io.StringIO()
        with patch.object(mission_runs, 'check_client', side_effect=ValueError('fixture-secret-never-print')):
            with redirect_stdout(output):
                code = self.m.main(['--root', str(self.root), 'client', 'check', '--executable', sys.executable,
                                    '--manifest', 'vault/local/probe.json'])
        self.assertNotEqual(code, 0)
        self.assertNotIn('fixture-secret-never-print', output.getvalue())
        self.assertNotIn('No provider was called', output.getvalue())

    def setUp(self):
        super().setUp()
        self.assertIsNotNone(importlib.util.find_spec('missions'), 'mission backend not implemented')
        self.m = importlib.import_module('missions')
        self.db = importlib.import_module('mission_store')
        self.op_id = str(uuid.uuid4())

    def prepared_fixture(self, features=1, pbis=2):
        paths = self.tree(features, pbis)
        for path in paths:
            self.m.import_item(self.root, path, 0, str(uuid.uuid4()), TL if '/pbis/' in path else ACTOR)
        self.m.apply_config(self.root, self.configured(), None)
        self.paths = paths
        return dict(title='Fixture mission', feature_ids=[self.item_id(p) for p in paths if '/features/' in p],
                    priority=[self.item_id(p) for p in paths if '/pbis/' in p], overrides={}, scope_reference='Approved fixture scope'), ACTOR

    def test_repeat_returns_same_mission_and_single_event(self):
        request, actor = self.prepared_fixture()
        first = self.m.prepare_mission(self.root, request, self.op_id, actor)
        second = self.m.prepare_mission(self.root, request, self.op_id, actor)
        self.assertEqual(first['record_id'], second['record_id'])
        self.assertEqual(first['sequence'], second['sequence'])
        self.assertEqual(len(self.db.list_records(self.root, 'mission')), 1)
        self.assertEqual(self.m.mission_status(self.root, first['code'])['state'], 'prepared')
        import vault
        self.assertEqual(vault.check(self.root)['issues'], [])

    def test_configuration_change_does_not_rewrite_mission(self):
        request, actor = self.prepared_fixture()
        receipt = self.m.prepare_mission(self.root, request, self.op_id, actor)
        first = self.db.get_record(self.root, receipt['record_id'])
        current = load_config(self.root)
        self.m.apply_config(self.root, effective_config(current, {'agents': {'pm': {'model': 'fixture-b'}}}), config_digest(current))
        self.assertEqual(self.db.get_record(self.root, receipt['record_id']), first)
        status = self.m.mission_status(self.root, first['id'])
        self.assertFalse(status['runnable'])
        self.assertFalse(status['stale_inputs'])
        self.assertEqual(self.m.prepare_mission(self.root, request, self.op_id, actor)['sequence'], receipt['sequence'])

    def test_revision_and_operation_conflicts_are_read_only(self):
        request, actor = self.prepared_fixture()
        receipt = self.m.prepare_mission(self.root, request, self.op_id, actor)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'operation_conflict'):
            self.m.prepare_mission(self.root, dict(request, title='Changed'), self.op_id, actor)
        with self.assertRaisesRegex(ValueError, 'revision_conflict'):
            self.m.revise_mission(self.root, receipt['code'], request, 0, str(uuid.uuid4()), actor)
        with self.assertRaisesRegex(ValueError, 'config_conflict'):
            self.m.apply_config(self.root, self.configured(), None)
        self.assertEqual(self.snapshot(), before)

    def test_status_does_not_initialize_or_repair(self):
        project = self.root / 'vault/project.json'
        saved_project = project.read_bytes()
        project.unlink()
        before = self.snapshot()
        self.assertEqual(self.m.mission_status(self.root, 'M001')['state'], 'not_initialized')
        self.assertEqual(self.snapshot(), before)
        project.write_bytes(saved_project)
        path = self.root / DB
        path.parent.mkdir(parents=True)
        path.write_bytes(b'corrupt')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'invalid_store'):
            self.m.mission_status(self.root, 'M001')
        self.assertEqual(self.snapshot(), before)

    def test_projection_failure_recovers_without_duplicate(self):
        request, actor = self.prepared_fixture()
        with patch('missions.project_receipt', side_effect=OSError('fixture')):
            receipt = self.m.prepare_mission(self.root, request, self.op_id, actor)
        self.assertEqual(receipt['projection_state'], 'pending')
        self.assertEqual(self.m.mission_status(self.root, receipt['code'])['projection_state'], 'pending')
        recovered = self.m.prepare_mission(self.root, request, self.op_id, actor)
        self.assertEqual(recovered['sequence'], receipt['sequence'])
        self.assertEqual(recovered['projection_state'], 'current')
        self.assertEqual(len(self.db.list_records(self.root, 'mission')), 1)

    def test_recovery_after_first_database_transaction_rolls_back(self):
        with patch('missions.atomic_write', side_effect=OSError('synthetic interrupted first config')):
            with self.assertRaises(OSError):
                self.m.apply_config(self.root, self.configured(), None)
        self.assertFalse((self.root / 'youngcrow/agents.json').exists())
        before = self.snapshot()
        self.assertEqual(self.m.mission_status(self.root, 'M001')['state'], 'not_initialized')
        self.assertEqual(self.snapshot(), before)
        result = self.m.apply_config(self.root, self.configured(), None)
        self.assertEqual(result['gaps'], [])
        self.assertEqual(self.db.list_records(self.root, None), [])

    def test_recovery_after_real_hot_journal_preserves_committed_state(self):
        request, actor = self.prepared_fixture()
        receipt = self.m.prepare_mission(self.root, request, self.op_id, actor)
        original = self.db.get_record(self.root, receipt['record_id'])
        script = '''import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1], isolation_level=None)
db.execute('PRAGMA journal_mode=DELETE')
db.execute('PRAGMA cache_size=1')
db.execute('PRAGMA synchronous=FULL')
db.execute('BEGIN IMMEDIATE')
db.execute('UPDATE records SET snapshot=? WHERE id=?', ('x' * (2 * 1024 * 1024), sys.argv[2]))
os._exit(73)
'''
        child = subprocess.run([sys.executable, '-B', '-c', script, str(self.root / DB), receipt['record_id']], timeout=20)
        self.assertEqual(child.returncode, 73)
        journal = self.root / (DB + '-journal')
        self.assertTrue(journal.is_file())
        self.assertNotEqual(journal.read_bytes()[:8], b'\x00' * 8)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'invalid_store'):
            self.m.mission_status(self.root, receipt['code'])
        self.assertEqual(self.snapshot(), before)
        # Explicit repair recovers SQLite; status remains strictly read-only.
        self.assertEqual(self.m.repair(self.root, receipt['code'])['projection_state'], 'current')
        self.assertEqual(self.db.get_record(self.root, receipt['record_id']), original)
        self.assertEqual(self.m.repair(self.root, receipt['code'])['projection_state'], 'current')
        self.assertEqual(len(self.m.mission_status(self.root, receipt['code'])['events']), 1)

    def test_recovery_of_large_projection_preserves_human_edits(self):
        paths = self.tree(features=1, pbis=2)
        # Individually bounded sources aggregate to an operational note larger than 1 MiB.
        for i, path in enumerate(paths[-2:]):
            self.contract(path, acceptance=[f'{i}:{n}:' + 'x' * 7000 for n in range(90)])
            self.assertLess((self.root / path).stat().st_size, 1024 * 1024)
        for path in paths:
            self.m.import_item(self.root, path, 0, str(uuid.uuid4()), TL if '/pbis/' in path else ACTOR)
        self.m.apply_config(self.root, self.configured(), None)
        request = dict(title='Large valid mission', feature_ids=[self.item_id(paths[1])],
                       priority=[self.item_id(p) for p in paths[-2:]], overrides={}, scope_reference='Fixture')
        receipt = self.m.prepare_mission(self.root, request, self.op_id, ACTOR)
        self.assertEqual(receipt['projection_state'], 'current')
        path = self.root / receipt['paths'][0]
        self.assertGreater(path.stat().st_size, 1024 * 1024)
        self.assertEqual(self.m.mission_status(self.root, receipt['code'])['projection_state'], 'current')
        self.assertEqual(self.m.prepare_mission(self.root, request, self.op_id, ACTOR)['event_id'], receipt['event_id'])
        self.assertEqual(self.m.repair(self.root, receipt['code'])['projection_state'], 'current')
        request['title'] = 'Refined large mission'
        self.m.revise_mission(self.root, receipt['code'], request, 1, str(uuid.uuid4()), ACTOR)
        human = path.read_bytes() + b'\nPreserve human addition.\n'
        path.write_bytes(human)
        self.assertEqual(self.m.repair(self.root, receipt['code'])['projection_state'], 'conflict')
        self.assertEqual(path.read_bytes(), human)

    def test_private_and_linked_storage_is_rejected(self):
        path = self.write_item('epic')
        self.git('add', '-f', '--', path)
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.m.import_item(self.root, path, 0, self.op_id, ACTOR)
        self.assertEqual(self.snapshot(), before)
        self.git('rm', '--cached', '--', path)
        self.m.apply_config(self.root, self.configured(), None)
        for relative in (DB + '-journal', DB):
            source = self.root / 'shared-file'
            source.write_bytes(b'fixture')
            target = self.root / relative
            if target.exists():
                target.unlink()
            os.link(source, target)
            before = self.snapshot()
            with self.assertRaises(ValueError):
                self.m.import_item(self.root, path, 0, self.op_id, ACTOR)
            self.assertEqual(self.snapshot(), before)
            target.unlink(); source.unlink()

    def test_snapshot_staleness_and_source_identity(self):
        request, actor = self.prepared_fixture()
        receipt = self.m.prepare_mission(self.root, request, self.op_id, actor)
        saved = self.db.get_record(self.root, receipt['record_id'])
        profile = self.root / 'vault/product/profile.md'
        profile.write_text(profile.read_text(encoding='utf-8') + '\nChanged.\n', encoding='utf-8')
        self.assertTrue(self.m.mission_status(self.root, receipt['code'])['stale_inputs'])
        self.assertEqual(self.db.get_record(self.root, receipt['record_id']), saved)
        self.contract(self.paths[-1], project_id=str(uuid.uuid4()))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.m.import_item(self.root, self.paths[-1], 1, str(uuid.uuid4()), TL)
        self.assertEqual(self.snapshot(), before)

    def test_revisions_keep_all_refinement_events(self):
        request, actor = self.prepared_fixture()
        with patch('missions.utc_now', return_value='2026-10-03T12:00:00+00:00'):
            receipt = self.m.prepare_mission(self.root, request, self.op_id, actor)
        with patch('missions.utc_now', return_value='2026-10-03T11:00:00+00:00'):
            newer = self.m.revise_mission(self.root, receipt['code'], dict(request, title='Refined'), 1, str(uuid.uuid4()), actor)
        self.assertGreater(newer['sequence'], receipt['sequence'])
        status = self.m.mission_status(self.root, receipt['code'])
        self.assertEqual(len(status['events']), 2)
        self.assertEqual(status['events'][0]['created_at'], '2026-10-03T12:00:00+00:00')
        self.assertEqual(status['events'][1]['created_at'], '2026-10-03T11:00:00+00:00')

    def test_multiple_drafts_are_not_active_missions(self):
        request, actor = self.prepared_fixture(features=2)
        for _ in range(2):
            receipt = self.m.prepare_mission(self.root, request, str(uuid.uuid4()), actor)
            status = self.m.mission_status(self.root, receipt['code'])
            self.assertEqual(len(status['snapshot']['pbi_ids']), 4)
            self.assertFalse(status['runtime_available'])
            self.assertFalse(status['runnable'])
        self.assertEqual(len(self.db.list_records(self.root, 'mission')), 2)

    def test_no_advanced_transition_or_shell_execution(self):
        before = self.snapshot()
        for extra in ('status', 'completed', 'counters', 'deploy'):
            with self.assertRaises(ValueError):
                self.m.prepare_mission(self.root, {extra: 'secret-fixture'}, self.op_id, ACTOR)
        self.assertEqual(self.snapshot(), before)
        request, actor = self.prepared_fixture()
        self.contract(self.paths[-1], validation=['$(touch never-execute); rm -rf /'])
        self.m.import_item(self.root, self.paths[-1], 1, str(uuid.uuid4()), TL)
        receipt = self.m.prepare_mission(self.root, request, self.op_id, actor)
        self.assertFalse((self.root / 'never-execute').exists())
        self.assertEqual(self.m.mission_status(self.root, receipt['code'])['state'], 'prepared')

    def test_human_projection_edit_is_preserved(self):
        request, actor = self.prepared_fixture()
        receipt = self.m.prepare_mission(self.root, request, self.op_id, actor)
        path = self.root / receipt['paths'][0]
        path.write_text(path.read_text(encoding='utf-8') + '\nHuman addition.\n', encoding='utf-8')
        content = path.read_bytes()
        self.assertEqual(self.m.mission_status(self.root, receipt['code'])['projection_state'], 'conflict')
        result = self.m.repair(self.root, receipt['code'])
        self.assertEqual(result['projection_state'], 'conflict')
        self.assertEqual(path.read_bytes(), content)

    def test_capability_selection_does_not_activate_tools(self):
        from test_capabilities import CapabilityCase
        import capabilities
        fixture = CapabilityCase()
        fixture.root = self.root
        catalog = fixture.seed()
        cap = catalog[0]
        cap['expected']['contract_sha256'] = capabilities.contract_digest(cap)
        for client in cap['clients']:
            cap['expected']['files_sha256'][client] = capabilities.content_digest(self.root, cap['files']['common'] + cap['files'][client])
        fixture.save(catalog)
        request, actor = self.prepared_fixture()
        request['overrides'] = {'agents': {'pm': {'capabilities': ['sample', 'not-installed']}}}
        before = {p: v for p, v in self.snapshot().items() if p.startswith(('.claude/', '.codex/', '.mcp'))}
        receipt = self.m.prepare_mission(self.root, request, self.op_id, actor)
        status = self.m.mission_status(self.root, receipt['code'])
        self.assertEqual(status['state'], 'draft')
        self.assertIn('capability:not-installed:unknown', status['gaps'])
        known = next(c for c in status['snapshot']['capabilities'] if c['id'] == 'sample')
        self.assertEqual(known['state'], 'matched')
        self.assertEqual(known['contract_sha256'], cap['expected']['contract_sha256'])
        self.assertTrue(known['coverage'])
        self.assertEqual(before, {p: v for p, v in self.snapshot().items() if p.startswith(('.claude/', '.codex/', '.mcp'))})

    def test_cli_errors_are_sanitized(self):
        source = self.root / 'invalid.json'
        source.write_text('{"api_key":"secret-fixture"}', encoding='utf-8')
        output = io.StringIO()
        before = self.snapshot()
        with redirect_stdout(output):
            code = self.m.main(['--root', str(self.root), '--json', 'config', 'validate', '--input', 'invalid.json'])
        self.assertEqual(code, 2)
        self.assertNotIn('secret-fixture', output.getvalue())
        self.assertEqual(json.loads(output.getvalue())['schema_version'], 1)
        self.assertEqual(self.snapshot(), before)

    def test_request_accepts_optional_role_override_syntax(self):
        request = dict(title='Integration', feature_ids=[str(uuid.uuid4())], priority=[],
                       scope_reference='Approved', overrides={'agents': {'integration_specialist': {'model': 'fixture-b'}}})
        self.m.validate_request(request)

    def test_unknown_schema_and_foreign_store_are_read_only(self):
        self.m.apply_config(self.root, self.configured(), None)
        for column, value in [('schema_version', 2), ('project_id', str(uuid.uuid4()))]:
            with closing(sqlite3.connect(self.root / DB)) as conn:
                conn.execute('UPDATE metadata SET schema_version=1, project_id=?', (self.project_id,))
                conn.execute(f'UPDATE metadata SET {column}=?', (value,))
                conn.commit()
            before = self.snapshot()
            with self.assertRaisesRegex(ValueError, 'invalid_store'):
                self.m.apply_config(self.root, self.configured(), config_digest(load_config(self.root)))
            self.assertEqual(self.snapshot(), before)

    def test_import_rename_preserves_identity_and_rejects_live_collision(self):
        path = self.write_item('epic')
        first = self.m.import_item(self.root, path, 0, self.op_id, ACTOR)
        newer = path.replace('/index.md', '/renamed.md')
        (self.root / newer).write_bytes((self.root / path).read_bytes())
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'identity_conflict'):
            self.m.import_item(self.root, newer, 1, str(uuid.uuid4()), ACTOR)
        self.assertEqual(self.snapshot(), before)
        (self.root / path).unlink()
        second = self.m.import_item(self.root, newer, 1, str(uuid.uuid4()), ACTOR)
        self.assertEqual(first['record_id'], second['record_id'])
        self.assertEqual(first['code'], second['code'])
        self.assertEqual(second['revision'], 2)

    def test_negated_ignore_is_rejected_without_repair(self):
        path = self.write_item('epic')
        ignore = self.root / '.gitignore'
        ignore.write_text(ignore.read_text(encoding='utf-8') + '\n!/vault/local/\n', encoding='utf-8')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.m.import_item(self.root, path, 0, self.op_id, ACTOR)
        self.assertEqual(self.snapshot(), before)

    def test_first_import_with_wrong_revision_does_not_initialize_store(self):
        path = self.write_item('epic')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, 'revision_conflict'):
            self.m.import_item(self.root, path, 1, self.op_id, ACTOR)
        self.assertEqual(self.snapshot(), before)

    def test_incompatible_helper_fails_before_any_write(self):
        source = Path(__file__).resolve().parents[1] / 'scripts'
        target = self.root / 'scripts'
        target.mkdir()
        for name in ('missions', 'mission_config', 'mission_backlog', 'mission_store', 'mission_vault',
                     'capabilities', 'document_store', 'integrations', 'vault'):
            shutil.copyfile(source / (name + '.py'), target / (name + '.py'))
        (target / 'capabilities.py').write_text('# preserved legacy helper\n', encoding='utf-8')
        before = self.snapshot()
        result = subprocess.run([sys.executable, '-B', str(target / 'missions.py'), '--root', str(self.root), '--json', 'status', 'M001'],
                                capture_output=True, text=True, timeout=20)
        self.assertIn('"error": "incompatible_helper"', result.stdout, result.stderr)
        self.assertEqual(result.stderr, '')
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.snapshot(), before)

    def test_incomplete_criteria_and_external_dependency_stay_draft(self):
        request, actor = self.prepared_fixture()
        self.contract(self.paths[-1], dor=[], dependencies=[str(uuid.uuid4())])
        self.m.import_item(self.root, self.paths[-1], 1, str(uuid.uuid4()), TL)
        receipt = self.m.prepare_mission(self.root, request, self.op_id, actor)
        status = self.m.mission_status(self.root, receipt['code'])
        self.assertEqual(status['state'], 'draft')
        self.assertTrue(any('invalid_dependency' in gap for gap in status['gaps']))
        self.assertTrue(any(':dor' in gap for gap in status['gaps']))

    def test_incompatible_client_helper_is_rejected_before_any_write(self):
        before = self.snapshot()
        with patch.dict(sys.modules, {'mission_clients': object()}):
            with self.assertRaisesRegex(ValueError, '^incompatible_helper$'):
                self.m.runtime_helpers()
        self.assertEqual(self.snapshot(), before)

    def test_native_probe_requires_explicit_manifest(self):
        before = self.snapshot()
        smoke = Path(__file__).parent / 'smoke_mission_runtime.py'
        for arguments in (['--executable', sys.executable], ['--native-manifest', 'vault/local/absent.json']):
            result = subprocess.run([sys.executable, '-B', str(smoke), '--root', str(self.root), *arguments],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertIn('mission_runtime_smoke_failed', result.stdout)
        self.assertEqual(self.snapshot(), before)


if __name__ == '__main__':
    unittest.main()
