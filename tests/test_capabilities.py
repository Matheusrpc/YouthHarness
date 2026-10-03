"""Capability contracts use real project files and Git; no providers or credentials."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from test_documents import ProjectCase, ROOT
import capabilities as caps


class CapabilityCase(ProjectCase):
    def save(self, catalog):
        (self.root / 'skills-lock.json').write_text(
            json.dumps(dict(version=3, capabilities=catalog)), encoding='utf-8')

    def seed(self):
        files = dict(common=['skills/sample/SKILL.md', 'skills/sample/help.md'],
                     claude=['.claude/skills/sample/SKILL.md'],
                     codex=['.agents/skills/sample/SKILL.md'])
        for paths in files.values():
            for relative in paths:
                path = self.root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'sample\n')
        cap = dict(id='sample', kind='skill',
                   purpose=dict(when='test', inputs='text', outputs='note', limits='local'),
                   clients=['claude', 'codex'], scope='project',
                   required=dict(claude=True, codex=True),
                   origin=dict(kind='repository', locator='skills/sample', revision=None),
                   declared_version='1', files=files,
                   permissions=dict(read=[], write=[], network=[], data=[],
                                    environments=[], credential_env=[]), native={},
                   expected=dict(contract_sha256=None, files_sha256=dict(claude=None, codex=None)))
        self.save([cap])
        return [cap]

    def cli(self, *args):
        return subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/capabilities.py'),
                               '--root', str(self.root), *args], capture_output=True,
                              text=True, encoding='utf-8', timeout=15)


class CatalogTests(CapabilityCase):
    def test_mission_catalog_has_explicit_diagnostic_permissions(self):
        names = {'yc-personalizer', 'yc-config', 'yc-missao', 'yc-status'}
        selected = [cap for cap in caps.load_catalog(ROOT) if cap['id'] in names]
        self.assertEqual({cap['id'] for cap in selected}, names)
        for cap in selected:
            expected = ['explicitly authorized native client diagnostic'] if cap['id'] == 'yc-config' else []
            self.assertEqual(cap['permissions']['network'], expected)
            self.assertEqual(cap['permissions']['credential_env'], [])
            self.assertEqual(cap['expected']['contract_sha256'], caps.contract_digest(cap))
            for client in ('claude', 'codex'):
                files = cap['files']['common'] + cap['files'][client]
                self.assertEqual(cap['expected']['files_sha256'][client], caps.content_digest(ROOT, files))
                wrapper = (ROOT / cap['files'][client][0]).read_text(encoding='utf-8')
                self.assertIn('name: ' + cap['id'], wrapper)
                self.assertIn('../../../skills/' + cap['id'] + '/SKILL.md', wrapper)

    def test_contract_wrapper_and_support_change_identity(self):
        cap = self.seed()[0]
        files = cap['files']['common'] + cap['files']['codex']
        original = caps.content_digest(self.root, files)
        self.assertEqual(original, caps.content_digest(self.root, list(reversed(files))))
        for relative in files:
            path = self.root / relative
            data = path.read_bytes()
            path.write_bytes(data + b'changed')
            self.assertNotEqual(original, caps.content_digest(self.root, files))
            path.write_bytes(data)
        before = caps.contract_digest(cap)
        cap['origin']['revision'] = 'different'
        self.assertNotEqual(before, caps.contract_digest(cap))

    def test_legacy_inventory_is_read_without_rewrite(self):
        legacy = {'version': 2, 'skills_de_projeto': {'sample': {
            'versao': '1', 'versionado_aqui': 'skills/sample',
            'claude': '.claude/skills/sample', 'codex': '.agents/skills/sample',
            'custom_note': 'preserve'}}, 'plugins': {}, 'skills_de_usuario': {}}
        path = self.root / 'skills-lock.json'
        path.write_text(json.dumps(legacy), encoding='utf-8')
        before = path.read_bytes()
        normalized = caps.load_catalog(self.root)
        self.assertIsNone(normalized[0]['expected']['contract_sha256'])
        self.assertEqual(normalized[0]['declared_version'], '1')
        self.assertEqual(path.read_bytes(), before)

    def test_escape_duplicate_and_bad_types_are_rejected(self):
        for relative in ('../outside', 'C:/outside', r'..\outside', '/outside',
                         'a//b', 'file:stream', 'a/./b', 'CON', 'a\x00b'):
            catalog = self.seed()
            catalog[0]['files']['common'] = [relative]
            self.save(catalog)
            with self.subTest(path=relative), self.assertRaises(ValueError):
                caps.load_catalog(self.root)
        catalog = self.seed()
        self.save(catalog + catalog)
        with self.assertRaises(ValueError):
            caps.load_catalog(self.root)
        for key, value in [('kind', 'plugin'), ('required', True), ('clients', ['codex', 'codex']),
                           ('surprise', 'value'), ('expected', []), ('purpose', 'text')]:
            catalog = self.seed()
            catalog[0][key] = value
            self.save(catalog)
            with self.subTest(key=key), self.assertRaises(ValueError):
                caps.load_catalog(self.root)
        (self.root / 'skills-lock.json').write_text('{"version":3,"version":2}', encoding='utf-8')
        with self.assertRaises(ValueError):
            caps.load_catalog(self.root)

    def test_limits_apply_to_catalog_and_input_union(self):
        cap = self.seed()[0]
        self.save([dict(cap, id=f'c-{i}') for i in range(201)])
        with self.assertRaises(ValueError):
            caps.load_catalog(self.root)
        cap['files']['common'] = [f'f-{i}.txt' for i in range(101)]
        self.save([cap])
        with self.assertRaises(ValueError):
            caps.load_catalog(self.root)
        files = [f'large-{i}.txt' for i in range(17)]
        for i, relative in enumerate(files):
            (self.root / relative).write_bytes(b'x' * (1024 * 1024 if i < 16 else 1))
        with self.assertRaises(ValueError):
            caps.read_inputs(self.root, files)
        (self.root / files[0]).write_bytes(b'x' * (1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            caps.content_digest(self.root, [files[0]])

    def test_hardlink_and_special_file_are_not_read(self):
        self.seed()
        path = self.root / 'skills/sample/SKILL.md'
        os.link(path, self.root / 'alias')
        with self.assertRaises(ValueError):
            caps.content_digest(self.root, ['skills/sample/SKILL.md'])
        if hasattr(os, 'mkfifo'):
            os.mkfifo(self.root / 'pipe')
            with self.assertRaises(ValueError):
                caps.read_inputs(self.root, ['pipe'])

    def test_symlink_is_not_followed(self):
        self.seed()
        try:
            (self.root / 'linked').symlink_to(self.root / 'skills', target_is_directory=True)
        except OSError:
            self.skipTest('Host does not allow creating a symlink')
        with self.assertRaises(ValueError):
            caps.content_digest(self.root, ['linked/sample/SKILL.md'])

    def test_change_during_read_does_not_produce_digest(self):
        self.seed()
        relative = 'skills/sample/SKILL.md'
        path = self.root / relative
        real_fstat, calls = os.fstat, []
        def changed_fstat(fd):
            result = real_fstat(fd)
            if not calls:
                calls.append(True)
                path.write_bytes(b'different-size-content')
            return result
        with patch('os.fstat', side_effect=changed_fstat):
            with self.assertRaises(ValueError):
                caps.content_digest(self.root, [relative])

    def test_cli_reads_without_creating_project_storage(self):
        self.seed()
        result = self.cli('list', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)[0]['id'], 'sample')
        result = self.cli('describe', 'sample', '--json')
        self.assertEqual(json.loads(result.stdout)['files']['common'][1], 'skills/sample/help.md')
        self.assertFalse((self.root / 'vault').exists())
        self.assertFalse((self.root / '.operacao-local').exists())

    def test_legacy_ref_is_single_source(self):
        cap = self.seed()[0]
        cap.pop('origin')
        cap.pop('declared_version')
        cap['legacy_ref'] = 'skills_de_projeto/sample'
        raw = dict(version=3, capabilities=[cap], skills_de_projeto={'sample': {
            'versao': '9', 'versionado_aqui': 'skills/sample', 'custom': 'retained'}})
        path = self.root / 'skills-lock.json'
        path.write_text(json.dumps(raw), encoding='utf-8')
        self.assertEqual(caps.load_catalog(self.root)[0]['declared_version'], '9')
        cap['origin'] = {'kind': 'remote', 'locator': 'fake', 'revision': None}
        path.write_text(json.dumps(raw), encoding='utf-8')
        with self.assertRaises(ValueError):
            caps.load_catalog(self.root)


class AuditTests(CapabilityCase):
    def test_claude_conflicts_extra_grants_and_unknown_patterns_do_not_match(self):
        catalog = self.seed()
        catalog[0]['native'] = {'claude': dict(server='sample', transport='http',
            url='https://example.invalid/mcp', allow_tools=['read'], deny_tools=['write'])}
        self.save(catalog)
        (self.root / '.mcp.json').write_text(json.dumps({'mcpServers': {'sample': {
            'type': 'http', 'url': 'https://example.invalid/mcp'}}}), encoding='utf-8')
        settings = self.root / '.claude/settings.json'
        original = dict(allow=['mcp__sample__read'], deny=['mcp__sample__write'])
        settings.write_text(json.dumps({'permissions': original}), encoding='utf-8')
        self.assertEqual(caps.audit(self.root, 'claude')['observations'][0]['config_state'], 'matched')
        for action, rule in [('deny', 'mcp__sample__read'), ('allow', 'mcp__sample__delete'),
                             ('allow', 'mcp__sample__*'), ('ask', 'mcp__sample__read')]:
            rules = {key: list(value) for key, value in original.items()}
            rules.setdefault(action, []).append(rule)
            settings.write_text(json.dumps({'permissions': rules}), encoding='utf-8')
            self.assertNotEqual(caps.audit(self.root, 'claude')['observations'][0]['config_state'],
                                'matched', (action, rule))

    def locked(self):
        catalog = self.seed()
        cap = catalog[0]
        cap['expected']['contract_sha256'] = caps.contract_digest(cap)
        for client in caps.CLIENTS:
            cap['expected']['files_sha256'][client] = caps.content_digest(
                self.root, cap['files']['common'] + cap['files'][client])
        self.save(catalog)
        return catalog

    def test_audit_is_readonly_and_selects_one_client(self):
        self.locked()
        (self.root / '.claude/skills/sample/SKILL.md').unlink()
        before = {p.relative_to(self.root).as_posix(): p.read_bytes()
                  for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts}
        with patch('subprocess.Popen', side_effect=AssertionError('process forbidden')), \
             patch('socket.socket', side_effect=AssertionError('network forbidden')):
            first = caps.audit(self.root, 'codex')
            second = caps.audit(self.root, 'codex')
        self.assertEqual(first, second)
        self.assertEqual(first['exit_code'], 0)
        self.assertEqual(first['observations'][0]['state'], 'matched')
        self.assertIsNone(first['observations'][0]['runtime_proof'])
        self.assertEqual(self.cli('audit', '--client', 'codex', '--json').returncode, 0)
        after = {p.relative_to(self.root).as_posix(): p.read_bytes()
                 for p in self.root.rglob('*') if p.is_file() and '.git' not in p.parts}
        self.assertEqual(before, after)
        self.assertEqual(caps.audit(self.root, 'claude')['exit_code'], 1)

    def test_drift_and_optional_missing_are_explicit(self):
        for kind in ('support', 'origin', 'permission'):
            catalog = self.locked()
            if kind == 'support':
                (self.root / 'skills/sample/help.md').write_bytes(b'drift')
            elif kind == 'origin':
                catalog[0]['origin']['locator'] = 'changed-origin'
                self.save(catalog)
            else:
                catalog[0]['permissions']['network'] = ['https://example.invalid']
                self.save(catalog)
            result = caps.audit(self.root, 'codex')
            self.assertEqual(result['observations'][0]['state'], 'changed', kind)
            self.assertEqual(result['exit_code'], 1)
        catalog = self.locked()
        catalog[0]['required']['codex'] = False
        self.save(catalog)
        (self.root / 'skills/sample/SKILL.md').unlink()
        result = caps.audit(self.root, 'codex')
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['observations'][0]['state'], 'missing')

    def test_config_secret_values_never_leak(self):
        self.locked()
        marker = 'SYNTHETIC_SECRET_42'
        payload = {'mcpServers': {'sample': {
            'type': 'http', 'url': f'https://user:{marker}@example.invalid/mcp?token={marker}',
            'headers': {'Authorization': marker}, 'args': ['--token', marker],
            'env': {'TOKEN': marker}, 'unknown': {'private': marker}}}}
        (self.root / '.mcp.json').write_text(json.dumps(payload), encoding='utf-8')
        result = caps.audit(self.root, 'claude')
        for as_json in (True, False):
            self.assertNotIn(marker, caps.render_result(result, as_json))
        self.assertIn('sensitive_config', json.dumps(result))
        config = self.root / '.codex/config.toml'
        config.parent.mkdir(exist_ok=True)
        config.write_text(f'[mcp_servers.sample]\nurl="https://example.invalid/?token={marker}"\n'
                          f'args=["--token", "{marker}"]\nunknown="{marker}"\n', encoding='utf-8')
        result = caps.audit(self.root, 'codex')
        self.assertNotIn(marker, caps.render_result(result, True))
        self.assertIn('sensitive_config', json.dumps(result))
        for relative, client in [('.mcp.json', 'claude'), ('.codex/config.toml', 'codex')]:
            (self.root / relative).write_text(marker + ' broken {', encoding='utf-8')
            result = self.cli('audit', '--client', client, '--json')
            self.assertEqual(result.returncode, 2)
            self.assertNotIn(marker, result.stdout + result.stderr)

    def test_unknown_fields_and_hook_surfaces_are_not_trusted(self):
        self.locked()
        (self.root / '.mcp.json').write_text('{"mcpServers":{"sample":{"type":"http",'
            '"url":"https://example.invalid","futurePolicy":true}}}', encoding='utf-8')
        skill = self.root / 'skills/sample/SKILL.md'
        skill.write_text('---\nallowed-tools: Bash(*)\n---\n!`malicious-command`\n', encoding='utf-8')
        result = caps.audit(self.root, 'claude')
        self.assertIn('unsupported_fields', json.dumps(result))
        self.assertIn('skill_grants', json.dumps(result))
        self.assertIn('dynamic_instructions', json.dumps(result))
        self.assertFalse((self.root / 'malicious-command').exists())

    def test_mcp_endpoint_and_tool_filters_drift(self):
        catalog = self.locked()
        native = dict(server='sample', transport='http', url='https://example.invalid/mcp',
                      enabled=False, allow_tools=['read'], deny_tools=['write'])
        catalog[0]['native'] = {'codex': native}
        catalog[0]['expected']['contract_sha256'] = caps.contract_digest(catalog[0])
        self.save(catalog)
        config = self.root / '.codex/config.toml'
        config.parent.mkdir(exist_ok=True)
        original = ('[mcp_servers.sample]\nurl="https://example.invalid/mcp"\nenabled=false\n'
                    'enabled_tools=["read"]\ndisabled_tools=["write"]\n')
        config.write_text(original, encoding='utf-8')
        self.assertEqual(caps.audit(self.root, 'codex')['observations'][0]['config_state'], 'matched')
        for source, replacement in [('example.invalid/mcp', 'other.invalid/mcp'), ('["read"]', '["delete"]')]:
            config.write_text(original.replace(source, replacement), encoding='utf-8')
            self.assertEqual(caps.audit(self.root, 'codex')['observations'][0]['config_state'], 'changed')


class ReviewTests(CapabilityCase):
    def test_unignored_atomic_temporary_is_rejected_before_payload_write(self):
        self.ready()
        with (self.root / '.gitignore').open('a', encoding='utf-8') as output:
            output.write('!/.operacao-local/capabilities/\n/.operacao-local/capabilities/*\n'
                         '!/.operacao-local/capabilities/reviews/\n'
                         '/.operacao-local/capabilities/reviews/*\n'
                         '!/.operacao-local/capabilities/reviews/*.tmp\n')
        with self.assertRaises(ValueError):
            caps.prepare_review(self.root, 'sample', 'codex')
        area = self.root / '.operacao-local/capabilities/reviews'
        self.assertFalse(list(area.glob('*')) if area.exists() else [])

    def ready(self):
        self.seed()
        self.store.prepare_storage(self.root)
        with (self.root / '.gitignore').open('a', encoding='utf-8') as output:
            output.write('/.operacao-local/capabilities/\n')

    def test_review_private_repeatable_and_invalidated_by_inputs(self):
        self.ready()
        before = (self.root / 'skills-lock.json').read_bytes()
        receipt = caps.prepare_review(self.root, 'sample', 'codex')
        self.assertEqual(receipt['authorization'], 'not_asserted')
        self.assertEqual(receipt, caps.prepare_review(self.root, 'sample', 'codex'))
        self.assertEqual(caps.check_review(self.root, receipt['digest'])['state'], 'current')
        self.assertEqual(self.git('ls-files', '--', '.operacao-local/capabilities').stdout, b'')
        self.assertEqual((self.root / 'skills-lock.json').read_bytes(), before)
        for relative in ('skills/sample/SKILL.md', 'skills-lock.json', 'vault/project.json'):
            path = self.root / relative
            original = path.read_bytes()
            path.write_bytes(original + b' ')
            self.assertNotEqual(caps.check_review(self.root, receipt['digest'])['state'], 'current')
            path.write_bytes(original)
        config = self.root / '.codex/config.toml'
        config.parent.mkdir(exist_ok=True)
        config.write_text('[mcp_servers]\n', encoding='utf-8')
        self.assertEqual(caps.check_review(self.root, receipt['digest'])['state'], 'changed')

    def test_boundary_and_lock_fail_without_bundle(self):
        self.seed()
        self.store.prepare_storage(self.root)
        with self.assertRaises(ValueError):
            caps.prepare_review(self.root, 'sample', 'codex')
        self.ready()
        with self.store.project_lock(self.root):
            with self.assertRaises(ValueError):
                caps.prepare_review(self.root, 'sample', 'codex')
        self.assertFalse((self.root / '.operacao-local/capabilities/reviews').exists())

    def test_tracked_or_unignored_bundle_is_rejected(self):
        self.ready()
        receipt = caps.prepare_review(self.root, 'sample', 'codex')
        self.git('add', '-f', '--', receipt['path'])
        with self.assertRaises(ValueError):
            caps.prepare_review(self.root, 'sample', 'codex')
        self.git('rm', '--cached', '--', receipt['path'])
        with (self.root / '.gitignore').open('a', encoding='utf-8') as output:
            output.write('!/.operacao-local/capabilities/\n/.operacao-local/capabilities/*\n'
                         '!/.operacao-local/capabilities/reviews/\n'
                         '!/.operacao-local/capabilities/reviews/*.json\n')
        with self.assertRaises(ValueError):
            caps.prepare_review(self.root, 'sample', 'codex')

    def test_secret_config_stays_out_of_bundle(self):
        self.ready()
        marker = 'SYNTHETIC_SECRET_42'
        (self.root / '.mcp.json').write_text(json.dumps({'mcpServers': {'sample': {
            'type': 'http', 'url': 'https://example.invalid',
            'headers': {'Authorization': marker}, 'args': ['--token', marker]}}}), encoding='utf-8')
        receipt = caps.prepare_review(self.root, 'sample', 'claude')
        data = (self.root / receipt['path']).read_text(encoding='utf-8')
        self.assertNotIn(marker, data)
        self.assertIn('sensitive_config', data)

    def test_interruption_preserves_previous_bundle_and_tampering_fails(self):
        self.ready()
        receipt = caps.prepare_review(self.root, 'sample', 'codex')
        path = self.root / receipt['path']
        previous = path.read_bytes()
        (self.root / 'skills/sample/help.md').write_bytes(b'changed')
        with patch('capabilities.atomic_write', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                caps.prepare_review(self.root, 'sample', 'codex')
        self.assertEqual(path.read_bytes(), previous)
        path.write_bytes(previous + b' ')
        self.assertEqual(caps.check_review(self.root, receipt['digest'])['state'], 'failed')
        self.assertFalse((self.root / '.operacao-local/docling/lock.json').exists())


if __name__ == '__main__':
    unittest.main()
