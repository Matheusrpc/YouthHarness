"""Breaks caught: implicit billing, stale policy, unsupported effort and false success."""
import copy
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))


def catalog(client):
    if client == 'codex':
        return [{'model': 'fixture-current', 'displayName': 'Current', 'isDefault': True,
                 'defaultReasoningEffort': 'medium',
                 'supportedReasoningEfforts': [{'reasoningEffort': v} for v in ['low', 'medium', 'high', 'max']]},
                {'model': 'fixture-fast', 'displayName': 'Fast', 'isDefault': False,
                 'defaultReasoningEffort': 'low', 'supportedReasoningEfforts': [{'reasoningEffort': 'low'}]}]
    return [{'value': 'default', 'resolvedModel': 'fixture-current', 'displayName': 'Default',
             'supportedEffortLevels': ['low', 'medium', 'high', 'max'], 'supportsEffort': True},
            {'value': 'fast', 'resolvedModel': 'fixture-fast', 'displayName': 'Fast',
             'supportedEffortLevels': ['low'], 'supportsEffort': True}]


def native_events(client, nonce):
    message = json.dumps({'probe_id': nonce})
    if client == 'codex':
        return [{'type': 'thread.started', 'thread_id': 'fixture'}, {'type': 'turn.started'},
                {'type': 'item.completed', 'item': {'id': 'i1', 'type': 'agent_message', 'text': message}},
                {'type': 'turn.completed', 'usage': {'input_tokens': 10, 'output_tokens': 5}}]
    return [{'type': 'system', 'subtype': 'init', 'model': 'fixture-current', 'tools': []},
            {'type': 'assistant', 'message': {'model': 'fixture-current', 'content': [{'type': 'text', 'text': message}]}},
            {'type': 'result', 'subtype': 'success', 'is_error': False, 'result': message,
             'num_turns': 1, 'usage': {'input_tokens': 10, 'output_tokens': 5}, 'total_cost_usd': 0.001}]


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('mission_clients'), 'mission_clients not implemented')
        self.module = importlib.import_module('mission_clients')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.executable = self.root / ('client.exe' if os.name == 'nt' else 'client')
        shutil.copyfile(sys.executable, self.executable)
        self.env = patch.dict(os.environ, {'HOME': str(self.root / 'home'),
                                          'USERPROFILE': str(self.root / 'home')}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.manifest = dict(schema_version=1, mission_id=str(uuid.uuid4()), mission_revision=1,
                             role='pm', operation_id=str(uuid.uuid4()), authorization_ref='fixture approval',
                             agent_seconds=10, max_runs=1, api_budget_usd=None, fixture_id='echo-v1')

    def snapshot(self):
        return {str(p.relative_to(self.root)): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def observation(self, client='codex'):
        # Only external CLI discovery is replaced. Hash/path/policy and adapters remain real.
        with patch.object(self.module, 'discover', return_value={
                'version': '0.146.0' if client == 'codex' else '2.1.220',
                'models': catalog(client), 'controls': True, 'auth_kind': 'authenticated', 'profile_verified': True}):
            return self.module.inspect_client(self.root, client, self.executable)

    def agent(self, client='codex', **patches):
        result = dict(client=client, connection='authenticated', model='latest',
                      effort={'level': 'medium', 'native_value': None}, credential_env=None, capabilities=[])
        result.update(patches)
        return result

    def test_inspection_never_verifies_model_or_changes_project(self):
        before = self.snapshot()
        result = self.observation()
        self.assertEqual(result['model_compatibility'], 'not_verified')
        self.assertEqual(before, self.snapshot())

    def test_conflicting_api_environment_blocks_authenticated_check(self):
        for client, key in [('codex', 'OPENAI_API_KEY'), ('claude', 'ANTHROPIC_API_KEY')]:
            observation = self.observation(client)
            with patch.dict(os.environ, {key: 'fixture-secret-never-print'}):
                with self.assertRaisesRegex(ValueError, '^connection_conflict$'):
                    self.module.build_check(self.agent(client), observation, self.manifest)

    def test_latest_uses_live_catalog_and_keeps_request_distinct(self):
        for client in ('codex', 'claude'):
            observation = self.observation(client)
            plan = self.module.build_check(self.agent(client), observation, self.manifest)
            self.assertEqual(plan['requested_model'], 'latest')
            self.assertEqual(plan['resolved_model'], 'fixture-current')
            self.assertIsInstance(plan['argv'], list)
            self.assertNotIn('fixture-fast', plan['argv'])
            updated = catalog(client)
            updated[0]['model' if client == 'codex' else 'resolvedModel'] = 'fixture-new-release'
            with patch.object(self.module, 'discover', return_value={'version': observation['version'],
                                                                   'models': updated, 'controls': True, 'auth_kind': 'authenticated', 'profile_verified': True}):
                newer = self.module.inspect_client(self.root, client, self.executable)
            self.assertEqual(self.module.build_check(self.agent(client), newer, self.manifest)['resolved_model'],
                             'fixture-new-release')

    def test_unknown_effort_is_not_downgraded(self):
        for client in ('codex', 'claude'):
            observation = self.observation(client)
            with self.assertRaisesRegex(ValueError, 'unsupported_combination'):
                self.module.build_check(self.agent(client, model='fixture-fast'), observation, self.manifest)
            with self.assertRaisesRegex(ValueError, 'unsupported_combination'):
                self.module.build_check(self.agent(client, effort={'level': 'native', 'native_value': 'invented'}),
                                        observation, self.manifest)
            plan = self.module.build_check(self.agent(client, effort={'level': 'native', 'native_value': 'max'}),
                                           observation, self.manifest)
            self.assertEqual(plan['requested_effort'], 'max')

    def test_changed_binary_invalidates_observation(self):
        observation = self.observation()
        with self.executable.open('ab') as stream:
            stream.write(b'changed')
        with self.assertRaisesRegex(ValueError, 'stale_observation'):
            self.module.build_check(self.agent(), observation, self.manifest)

    def test_managed_policy_gap_blocks_check(self):
        observation = self.observation()
        observation['gaps'] = ['managed_policy_unverified']
        with self.assertRaisesRegex(ValueError, 'unsupported_policy'):
            self.module.build_check(self.agent(), observation, self.manifest)

    def test_project_policy_change_invalidates_observation(self):
        observation = self.observation()
        (self.root / '.codex').mkdir()
        (self.root / '.codex/config.toml').write_text('model = "changed"', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'stale_observation'):
            self.module.build_check(self.agent(), observation, self.manifest)

    def test_api_is_explicit_and_secret_is_not_serialized(self):
        for client, key in [('codex', 'OPENAI_API_KEY'), ('claude', 'ANTHROPIC_API_KEY')]:
            observation = self.observation(client)
            manifest = dict(self.manifest, api_budget_usd='0.10')
            with patch.dict(os.environ, {key: 'fixture-secret-never-print'}):
                plan = self.module.build_check(self.agent(client, connection='api', credential_env=key), observation, manifest)
                self.assertEqual(plan['connection'], 'api')
                self.assertNotIn('fixture-secret-never-print', repr(plan))
                self.assertNotIn('fixture-secret-never-print', repr(observation))

    def test_duplicate_or_truncated_json_is_rejected(self):
        for payload in [b'{"type":"a","type":"b"}\n', b'{"type":', b'[]\n', b'{"x":"' + b'x' * 1048576 + b'"}\n']:
            with self.assertRaises(ValueError):
                self.module.parse_events(payload)

    def test_success_requires_nonce_terminal_event_and_no_tool_use(self):
        for client in ('codex', 'claude'):
            events = native_events(client, self.manifest['operation_id'])
            result = self.module.decode_result(client, events, self.manifest['operation_id'])
            self.assertEqual(result['state'], 'succeeded')
            self.assertEqual(result['usage']['input_tokens'], 10)
            with self.assertRaises(ValueError):
                self.module.decode_result(client, events[:-1], self.manifest['operation_id'])
            with self.assertRaises(ValueError):
                self.module.decode_result(client, events, str(uuid.uuid4()))
            changed = copy.deepcopy(events)
            if client == 'codex':
                changed.insert(2, {'type': 'item.started', 'item': {'type': 'command_execution', 'command': 'never run'}})
            else:
                changed[0]['tools'] = ['Bash']
            with self.assertRaisesRegex(ValueError, 'unexpected_tool'):
                self.module.decode_result(client, changed, self.manifest['operation_id'])

    def test_model_mismatch_is_not_success(self):
        events = native_events('claude', self.manifest['operation_id'])
        events[1]['message']['model'] = 'unrequested-fallback'
        with self.assertRaisesRegex(ValueError, 'model_mismatch'):
            self.module.decode_result('claude', events, self.manifest['operation_id'])

    def test_unknown_cost_and_model_are_not_invented(self):
        result = self.module.decode_result('codex', native_events('codex', self.manifest['operation_id']),
                                           self.manifest['operation_id'])
        self.assertIsNone(result['cost_usd'])
        self.assertIsNone(result['observed_model'])

    def test_ambiguous_default_and_missing_home_fail_closed(self):
        observation = self.observation()
        observation['models'][1]['is_default'] = True
        with self.assertRaisesRegex(ValueError, 'ambiguous_model'):
            self.module.build_check(self.agent(), observation, self.manifest)
        with patch.object(Path, 'home', side_effect=RuntimeError('private home')):
            with self.assertRaisesRegex(ValueError, '^unsupported_policy$'):
                self.observation()

    def test_malformed_nested_client_data_is_sanitized(self):
        for client in ('claude', 'codex'):
            events = native_events(client, self.manifest['operation_id'])
            events[-1]['usage'] = 'secret-provider-output'
            with self.assertRaisesRegex(ValueError, '^client_protocol_error$'):
                self.module.decode_result(client, events, self.manifest['operation_id'])

    def test_client_default_effort_supports_models_without_effort_control(self):
        observation = self.observation('claude')
        observation['models'][1]['efforts'] = []
        plan = self.module.build_check(self.agent('claude', model='fixture-fast',
                                      effort={'level': 'native', 'native_value': 'client-default'}), observation, self.manifest)
        self.assertEqual(plan['requested_effort'], 'client-default')
        self.assertNotIn('--effort', plan['argv'])

    def test_unknown_or_api_login_cannot_be_used_as_subscription(self):
        observation = self.observation()
        for auth in ('unknown', 'api'):
            observation['auth_kind'] = auth
            with self.assertRaisesRegex(ValueError, 'connection_unverified'):
                self.module.build_check(self.agent(), observation, self.manifest)

    def test_help_flags_do_not_prove_enforcement(self):
        with patch.object(self.module, 'discover', return_value=dict(version='0.146.0', models=catalog('codex'), controls=True)):
            observation = self.module.inspect_client(self.root, 'codex', self.executable)
        self.assertIn('native_profile_unverified', observation['gaps'])

    def test_loopback_tools_empty_does_not_certify_managed_policy(self):
        observed_hash = 'af5bf1f1b2aadffc768eccd787084c6fdf9ba81624cbe96c1c6d9ac1a1550231'
        with patch.object(self.module, 'hash_file', return_value=observed_hash), \
             patch.object(self.module, 'discover', return_value=dict(version='2.1.220', models=catalog('claude'), controls=True)):
            observation = self.module.inspect_client(self.root, 'claude', self.executable)
        self.assertIn('native_profile_unverified', observation['gaps'])


if __name__ == '__main__':
    unittest.main()
