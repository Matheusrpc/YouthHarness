"""Exercise the actual installer without network, user plugins or real credentials."""
import json
import os
from pathlib import Path
import shutil
import shlex
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILES = ('setup.sh', 'CLAUDE.md', 'AGENTS.md', '.mcp.json', '.env.example',
         '.gitignore', '.codex/hooks.json', '.claude/settings.json',
         'skills-lock.json', 'docs/CLAUDE.en.md', 'skills/humanizer-ptbr/SKILL.md', '.codex/config.toml')
INTEGRATION_FILES = ('scripts/integrations.py', 'skills/integrate-from-docs/SKILL.md',
          'skills/integrate-from-docs/references/memory.md', 'vault/index.md',
          'vault/integrations/index.md', 'vault/capabilities/index.md',
          '.agents/skills/integrate-from-docs/SKILL.md', '.claude/skills/integrate-from-docs/SKILL.md',
          '.claude/agents/integration-specialist.md', '.codex/agents/integration-specialist.toml')
PERSONALIZER_FILES = ('scripts/personalize.py', 'skills/personalizer/SKILL.md',
                      'skills/personalizer/references/interview.md',
                      '.claude/skills/personalizer/SKILL.md', '.agents/skills/personalizer/SKILL.md')
FILES += INTEGRATION_FILES + PERSONALIZER_FILES + ('scripts/vault.py', 'scripts/document_store.py')
FILES += ('scripts/documents.py', 'scripts/docling_worker.py', 'requirements/docling.txt')
FILES += ('scripts/source_fetch.py',)
FILES += ('requirements/docling-media.txt',)
FILES += ('scripts/memory.py', 'scripts/graphify_worker.py', 'requirements/graphify.txt',
          'skills/retrieve-memory/SKILL.md', '.claude/skills/retrieve-memory/SKILL.md', '.agents/skills/retrieve-memory/SKILL.md')
FILES += ('scripts/source_prompt.py', 'skills/ingest-source/SKILL.md',
          '.claude/skills/ingest-source/SKILL.md', '.agents/skills/ingest-source/SKILL.md')
FILES += ('scripts/capabilities.py', 'skills/govern-capabilities/SKILL.md',
          '.claude/skills/govern-capabilities/SKILL.md', '.agents/skills/govern-capabilities/SKILL.md')
FILES += ('scripts/adoption.py', 'scripts/adoption_fs.py', 'scripts/adoption_acl.ps1')
FILES += tuple(f'scripts/{name}.py' for name in
               ('mission_config', 'mission_backlog', 'mission_store', 'mission_vault', 'missions',
                'mission_clients', 'mission_process', 'mission_runs'))
FILES += tuple(f'{base}/{name}/SKILL.md' for base in ('skills', '.claude/skills', '.agents/skills')
               for name in ('yc-personalizer', 'yc-config', 'yc-missao', 'yc-status'))


def shell_path(path):
    value = Path(path).absolute().as_posix()
    return '/' + value[0].lower() + value[2:] if os.name == 'nt' else value


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8', newline='\n')


def snapshot_bytes(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() if p.is_file() else None
            for p in root.rglob('*')}


def fake_git(args):
    with open(os.environ['TEST_CALLS'], 'a', encoding='utf-8') as log:
        log.write(json.dumps(['git', *args]) + '\n')
    if args and args[0] == 'clone':
        args = ['clone', '-q', '--', os.environ['TEST_UPSTREAM'], args[-1]]
    elif 'checkout' in args and os.environ.get('TEST_FAIL_CHECKOUT') == '1':
        return 17
    elif any(x in args for x in ('fetch', 'pull', 'push', 'ls-remote', 'submodule')):
        return 97
    return subprocess.run([os.environ['TEST_REAL_GIT'], *args]).returncode


class SetupTests(unittest.TestCase):
    def test_runtime_helpers_preserve_existing_install(self):
        write(self.target / 'scripts/mission_runs.py', '# human adapter\n')
        result = self.run_setup('--client', 'both', '--no-plugins', '--force', timeout=180)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.target / 'scripts/mission_runs.py').read_text(), '# human adapter\n')
        for name in ('mission_clients', 'mission_process'):
            self.assertTrue((self.target / f'scripts/{name}.py').is_file())
        self.assertFalse((self.target / 'vault/local/operations/state.sqlite3').exists())

    def test_mission_commands_follow_client_selection(self):
        names = ('yc-personalizer', 'yc-config', 'yc-missao', 'yc-status')
        for client in ('claude', 'codex', 'both'):
            with self.subTest(client=client):
                self.target = self.base / ('mission-' + client)
                self.target.mkdir()
                result = self.run_setup('--client', client, '--no-plugins')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                for name in names:
                    self.assertTrue((self.target / f'skills/{name}/SKILL.md').is_file())
                    for folder, selected in (('.claude', client in ('claude', 'both')), ('.agents', client in ('codex', 'both'))):
                        self.assertEqual((self.target / f'{folder}/skills/{name}/SKILL.md').is_file(), selected)
                for script in ('mission_config', 'mission_backlog', 'mission_store', 'mission_vault', 'missions'):
                    self.assertTrue((self.target / f'scripts/{script}.py').is_file())
                self.assertFalse((self.target / 'youngcrow/agents.json').exists())
                self.assertIn('/vault/local/', (self.target / '.gitignore').read_text())
                audit = subprocess.run([sys.executable, '-B', str(self.target / 'scripts/capabilities.py'),
                                        '--root', str(self.target), 'audit', '--client', client, '--json'],
                                       capture_output=True, text=True, timeout=30)
                observations = [o for o in json.loads(audit.stdout)['observations'] if o['id'] in names]
                self.assertEqual(len(observations), len(names) * (2 if client == 'both' else 1))
                self.assertTrue(all(o['state'] == 'matched' for o in observations), observations)

    def test_mission_setup_preserves_existing_contracts(self):
        originals = {'youngcrow/agents.json': 'custom config', 'skills-lock.json': 'custom catalog',
                     'vault/local/product/feature.md': 'human UUID and text',
                     'skills/yc-config/SKILL.md': 'custom skill',
                     '.agents/skills/yc-config/SKILL.md': 'custom entry',
                     'scripts/capabilities.py': '# legacy helper preserved\n'}
        for name, content in originals.items():
            write(self.target / name, content)
        result = self.run_setup('--client', 'both', '--no-plugins')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, content in originals.items():
            self.assertEqual((self.target / name).read_text(), content)
        backend = self.target / 'scripts/missions.py'
        self.assertTrue(backend.exists())
        probe = subprocess.run([sys.executable, '-B', str(backend), '--root', str(self.target), '--json', 'status', 'M001'],
                               capture_output=True, text=True, timeout=20)
        self.assertEqual(json.loads(probe.stdout)['error'], 'incompatible_helper')
        preserved = {name: content for name, content in originals.items() if not name.startswith('scripts/')}
        result = self.run_setup('--client', 'both', '--no-plugins', '--force')
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name, content in preserved.items():
            self.assertEqual((self.target / name).read_text(), content)

    def test_mission_setup_rejects_missing_dependency(self):
        helper = self.source / 'scripts/mission_store.py'
        helper.unlink(missing_ok=True)
        before = snapshot_bytes(self.target)
        result = self.run_setup('--client', 'both', '--no-plugins')
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot_bytes(self.target), before)

    def adoption_status(self):
        result = subprocess.run([sys.executable, '-B', str(self.source / 'scripts/adoption.py'),
                                 '--root', str(self.target), '--backup-root', str(self.base / 'backups'),
                                 'status', '--json'], capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_trial_is_project_only_and_reuses_first_baseline(self):
        for client in ('claude', 'codex', 'both'):
            with self.subTest(client=client):
                self.target = self.base / ('trial-' + client)
                self.target.mkdir()
                write(self.target / 'user.txt', 'before')
                before_home = snapshot_bytes(self.home)
                args = ('--trial', '--backup-root', shell_path(self.base / 'backups'), '--client', client)
                first = self.run_setup(*args)
                self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
                initial = self.adoption_status()
                self.assertEqual(initial['state'], 'installed')
                write(self.target / 'user.txt', 'trial work')
                repeated = self.run_setup(*args, '--force')
                self.assertEqual(repeated.returncode, 0, repeated.stdout + repeated.stderr)
                self.assertEqual(self.adoption_status()['baseline_digest'], initial['baseline_digest'])
                self.assertEqual(snapshot_bytes(self.home), before_home)
                calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
                self.assertFalse(any(call[0] == 'claude' or 'clone' in call[1:] for call in calls))

    def test_trial_missing_target_has_absent_baseline(self):
        self.target.rmdir()
        result = self.run_setup('--trial', '--backup-root', shell_path(self.base / 'backups'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse(self.adoption_status()['root_exists'])

    def test_trial_internal_flag_cannot_be_forged(self):
        before = snapshot_bytes(self.target)
        result = self.run_setup('--trial-child', env={'YOUNGCROW_ADOPTION_TOKEN': 'forged',
                                                     'YOUNGCROW_ADOPTION_BASE': str(self.base / 'backups')})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot_bytes(self.target), before)

    def test_trial_refuses_unsupported_source_before_writes(self):
        write(self.target / 'original', 'keep')
        os.link(self.target / 'original', self.target / 'alias')
        before = snapshot_bytes(self.target)
        result = self.run_setup('--trial', '--backup-root', shell_path(self.base / 'backups'))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot_bytes(self.target), before)

    def test_trial_partial_failure_retains_baseline_and_repeats(self):
        write(self.target / 'original', 'keep')
        installer = self.source / 'setup.sh'
        original = installer.read_text(encoding='utf-8')
        marker = '  local rel="$1" src="$HARNESS_DIR/$1" dst="$TARGET/$1"\n'
        self.assertEqual(original.count(marker), 1)
        # Fail inside this disposable installer; Git Bash launchers can reorder PATH.
        write(installer, original.replace(marker, marker + '  [ "$rel" != AGENTS.md ] || exit 19\n'))
        args = ('--trial', '--backup-root', shell_path(self.base / 'backups'))
        failed = self.run_setup(*args)
        self.assertEqual(failed.returncode, 19, failed.stdout + failed.stderr)
        initial = self.adoption_status()
        self.assertEqual(initial['state'], 'install_failed')
        self.assertTrue((self.target / 'CLAUDE.md').exists())
        write(installer, original)
        result = self.run_setup(*args)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.adoption_status()['baseline_digest'], initial['baseline_digest'])

    def test_trial_git_configuration_cannot_write_before_refusal(self):
        self.git('init', '-q', str(self.target))
        write(self.target / 'tracked', 'keep')
        self.git('-C', str(self.target), 'add', 'tracked')
        os.link(self.target / 'tracked', self.target / 'alias')
        command = 'echo UNEXPECTED > marker.txt; echo UNEXPECTED > "$HOME/marker.txt"'
        self.git('-C', str(self.target), 'config', 'core.fsmonitor', command)
        before, profile = snapshot_bytes(self.target), snapshot_bytes(self.home)
        result = self.run_setup('--trial', '--backup-root', shell_path(self.base / 'backups'),
                                env={'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'core.fsmonitor',
                                     'GIT_CONFIG_VALUE_0': command})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot_bytes(self.target), before)
        self.assertEqual(snapshot_bytes(self.home), profile)
        self.assertFalse((self.base / 'backups').exists())

    def test_trial_git_configuration_is_disabled_in_installer_child(self):
        self.git('init', '-q', str(self.target))
        write(self.target / 'tracked', 'keep')
        self.git('-C', str(self.target), 'add', 'tracked')
        command = 'echo UNEXPECTED > marker.txt; echo UNEXPECTED > "$HOME/marker.txt"'
        self.git('-C', str(self.target), 'config', 'core.fsmonitor', command)
        profile = snapshot_bytes(self.home)
        result = self.run_setup('--trial', '--backup-root', shell_path(self.base / 'backups'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.target / 'marker.txt').exists())
        self.assertEqual(snapshot_bytes(self.home), profile)
        self.assertEqual(self.adoption_status()['state'], 'installed')

    def test_trial_refuses_legacy_without_prior_baseline(self):
        for name in ('skills-lock.json', 'scripts/vault.py', 'skills/personalizer/SKILL.md'):
            write(self.target / name, 'existing')
        before = snapshot_bytes(self.target)
        result = self.run_setup('--trial', '--backup-root', shell_path(self.base / 'backups'))
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(snapshot_bytes(self.target), before)

    @unittest.skipUnless(os.name == 'nt', 'native PowerShell path limit')
    def test_trial_deep_backup_is_refused_before_first_write(self):
        parent = self.base / ('long-' + 'x' * 70)
        parent.mkdir()
        write(self.target / 'original', 'keep')
        before = snapshot_bytes(self.target)
        result = self.run_setup('--trial', '--backup-root', shell_path(parent / 'backups'))
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('unsupported_path_length', result.stderr)
        self.assertEqual(snapshot_bytes(self.target), before)
        self.assertFalse((parent / 'backups').exists())

    def test_governance_preserves_local_contracts_even_with_force(self):
        preserved = ('.mcp.json', '.codex/config.toml', '.claude/settings.json',
                     '.codex/hooks.json', 'skills-lock.json', 'skills/personalizer/SKILL.md',
                     '.agents/skills/personalizer/SKILL.md', '.env')
        for relative in preserved:
            write(self.target / relative, 'CUSTOM_SENTINEL\n')
        result = self.run_setup('--client', 'both', '--no-plugins', '--force')
        self.assertEqual(result.returncode, 0, result.stderr)
        for relative in preserved:
            self.assertEqual((self.target / relative).read_text(), 'CUSTOM_SENTINEL\n', relative)
        for directory in ('.claude', '.agents'):
            self.assertTrue((self.target / directory / 'skills/govern-capabilities/SKILL.md').is_file())
        self.assertIn('/.operacao-local/capabilities/', (self.target / '.gitignore').read_text())

    def test_governance_installs_selected_profiles_and_audits(self):
        for client in ('claude', 'codex', 'both'):
            with self.subTest(client=client):
                self.target = self.base / ('governance-' + client)
                self.target.mkdir()
                result = self.run_setup('--client', client, '--no-plugins')
                self.assertEqual(result.returncode, 0, result.stderr)
                for directory, selected in (('.claude', client != 'codex'), ('.agents', client != 'claude')):
                    self.assertEqual((self.target / directory / 'skills/govern-capabilities/SKILL.md').is_file(), selected)
                audit = subprocess.run([sys.executable, '-B', str(self.target / 'scripts/capabilities.py'),
                                        '--root', str(self.target), 'audit', '--client', client, '--json'],
                                       capture_output=True, text=True, timeout=15)
                self.assertEqual(audit.returncode, 0, audit.stdout + audit.stderr)
                observed = json.loads(audit.stdout)['observations']
                self.assertTrue(any(o['id'] == 'govern-capabilities' and o['state'] == 'matched' for o in observed))

    def test_memory_skill_preserves_existing_client_settings(self):
        for client in ('claude', 'codex', 'both'):
            with self.subTest(client=client):
                self.target = self.base / ('memory-' + client)
                self.target.mkdir()
                preserved = ('.mcp.json', '.codex/config.toml', '.claude/settings.json', '.codex/hooks.json')
                for name in preserved:
                    write(self.target / name, 'CUSTOM_SENTINEL\n')
                result = self.run_setup('--client', client, '--no-plugins', '--force')
                self.assertEqual(result.returncode, 0, result.stderr)
                for name in preserved:
                    self.assertEqual((self.target / name).read_text(), 'CUSTOM_SENTINEL\n')
                for directory, selected in (('.claude', client != 'codex'), ('.agents', client != 'claude')):
                    wrapper = self.target / directory / 'skills/retrieve-memory/SKILL.md'
                    self.assertEqual(wrapper.is_file(), selected)
                    if selected:
                        self.assertIn('skills/retrieve-memory/SKILL.md', wrapper.read_text())
                self.assertFalse((self.target / '.operacao-local/memory/runtime/venv').exists())

    def test_force_preserves_client_settings_and_credentials(self):
        originals = {name: 'CUSTOM_SENTINEL\n' for name in
                     ('.mcp.json', '.codex/config.toml', '.claude/settings.json', '.codex/hooks.json')}
        for name, content in originals.items():
            write(self.target / name, content)
        result = self.run_setup('--no-plugins', '--force')
        self.assertEqual(result.returncode, 0, result.stderr)
        for name, content in originals.items():
            self.assertEqual((self.target / name).read_text(), content, name)
        self.assertIn('merge', result.stdout)

    def setUp(self):
        self.bash = shutil.which('bash') or 'C:/Program Files/Git/bin/bash.exe'
        self.real_git = shutil.which('git')
        if not Path(self.bash).is_file() or not self.real_git:
            self.fail('Tests require Bash (Git Bash on Windows) and Git.')
        self.temp = tempfile.TemporaryDirectory(prefix='yc-')
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        boundary = subprocess.run([self.real_git, '-C', str(self.base), 'rev-parse', '--absolute-git-dir'],
                                  capture_output=True)
        self.assertNotEqual(boundary.returncode, 0, 'fixture must be outside Git')
        self.source, self.target = self.base / 'source', self.base / 'project with spaces'
        self.home, self.bin = self.base / 'home', self.base / 'bin'
        self.calls, self.upstream = self.base / 'calls.jsonl', self.base / 'upstream'
        self.calls.touch()  # No intercepted calls is a valid result for project-only trial.
        for folder in (self.source, self.target, self.home, self.bin, self.upstream):
            folder.mkdir()
        if os.name == 'nt':
            (self.home / 'AppData/Roaming').mkdir(parents=True)
            (self.home / 'AppData/Local').mkdir()
        for rel in FILES:
            dest = self.source / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / rel, dest)
        # Only OS necessities cross this boundary. No provider tokens or user Git settings.
        self.child_env = {key: value for key, value in os.environ.items()
                          if key.upper() in ('SYSTEMROOT', 'WINDIR', 'COMSPEC', 'TEMP', 'TMP', 'PATHEXT')}
        self.child_env.update(
            HOME=shell_path(self.home), USERPROFILE=str(self.home), TEST_BIN=shell_path(self.bin), TEST_GIT_BIN=shell_path(Path(self.real_git).parent),
            TEST_PYTHON=sys.executable.replace('\\', '/'), TEST_RUNNER=str(Path(__file__).resolve()).replace('\\', '/'),
            TEST_REAL_GIT=self.real_git, TEST_UPSTREAM=str(self.upstream), TEST_CALLS=str(self.calls),
            GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT='0',
            GIT_CEILING_DIRECTORIES=str(self.base),
            PATH=os.pathsep.join((str(Path(self.real_git).parent), str(Path(sys.executable).parent))),
        )
        self.git('init', '-q', str(self.upstream))
        write(self.upstream / 'SKILL.md', '---\nname: humanizer\ndescription: Local test skill fixture.\n---\n# Local test skill\n')
        self.git('-C', str(self.upstream), 'add', '--', 'SKILL.md')
        self.git('-C', str(self.upstream), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'test fixture')
        self.expected_commit = self.git('-C', str(self.upstream), 'rev-parse', 'HEAD').stdout.strip()
        manifest = json.loads((self.source / 'skills-lock.json').read_text(encoding='utf-8'))
        manifest['skills_de_usuario']['humanizer']['upstream']['commit'] = self.expected_commit
        write(self.source / 'skills-lock.json', json.dumps(manifest))
        self.wrapper('python3', 'exec "$TEST_PYTHON" "$@"')
        self.wrapper('git', 'exec "$TEST_PYTHON" "$TEST_RUNNER" --fake-git "$@"')
        self.wrapper('claude', 'exec "$TEST_PYTHON" "$TEST_RUNNER" --fake-claude "$@"')

    def wrapper(self, name, body):
        path = self.bin / name
        write(path, '#!/bin/bash\n' + body + '\n')
        path.chmod(0o755)

    def git(self, *args, check=True):
        return subprocess.run([self.real_git, *args], env=self.child_env, capture_output=True,
                              encoding='utf-8', check=check, timeout=20)

    def run_setup(self, *args, env=None, timeout=None):
        child = self.child_env.copy()
        child.update(env or {})
        return subprocess.run(
            [self.bash, '-c', 'export PATH="$TEST_BIN:$TEST_GIT_BIN:/usr/bin:/bin"; exec /usr/bin/bash "$@"',
             'test-setup', shell_path(self.source / 'setup.sh'), shell_path(self.target), *args],
            cwd=self.source, env=child, capture_output=True, encoding='utf-8', errors='replace',
            stdin=subprocess.DEVNULL, timeout=timeout or (180 if any('trial' in a for a in args) else 45))

    def assert_no_project_writes(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse((self.target / 'CLAUDE.md').exists())
        self.assertFalse((self.target / '.env').exists())

    def symlink(self, dest, source, directory=False):
        try:
            dest.symlink_to(source, target_is_directory=directory)
        except OSError as error:
            if os.name == 'nt' and getattr(error, 'winerror', None) == 1314:
                self.skipTest('Windows needs Developer Mode or symlink privilege; Linux CI must run this case.')
            raise

    def test_missing_name_fails_before_writes(self):
        result = self.run_setup('--nome')
        self.assertEqual(result.returncode, 2)
        self.assert_no_project_writes(result)

    def test_unknown_option_fails_before_writes(self):
        self.assert_no_project_writes(self.run_setup('--not-an-option'))

    def test_broken_python_fails_before_writes(self):
        self.wrapper('python3', 'exit 127')
        self.assert_no_project_writes(self.run_setup('--sem-plugins'))

    def test_bad_manifest_fails_before_writes(self):
        write(self.source / 'skills-lock.json', '{bad json')
        self.assert_no_project_writes(self.run_setup('--sem-plugins'))

    def test_managed_parent_file_fails_before_writes(self):
        write(self.target / '.claude', 'keep this')
        self.assert_no_project_writes(self.run_setup('--sem-plugins'))
        self.assertEqual((self.target / '.claude').read_text(), 'keep this')

    def test_dangling_env_link_is_rejected(self):
        missing = self.base / 'outside-env'
        self.symlink(self.target / '.env', missing)
        self.assert_no_project_writes(self.run_setup('--sem-plugins'))
        self.assertFalse(missing.exists())

    def test_directory_link_cannot_write_outside_project(self):
        outside = self.base / 'outside'
        outside.mkdir()
        write(outside / 'settings.json', 'sentinel')
        self.symlink(self.target / '.claude', outside, directory=True)
        self.assert_no_project_writes(self.run_setup('--sem-plugins', '--force'))
        self.assertEqual((outside / 'settings.json').read_text(), 'sentinel')

    def test_tool_interception(self):
        result = subprocess.run([self.bash, '-c',
                                 'export PATH="$TEST_BIN:/usr/bin:/bin"; command -v git; command -v claude'],
                                env=self.child_env, capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [shell_path(self.bin / 'git'), shell_path(self.bin / 'claude')])

    def test_existing_guide_is_preserved(self):
        guide = self.target / 'CLAUDE.md'
        original = b'# Keep {{PROJETO}} literally\r\n'
        guide.write_bytes(original)
        result = self.run_setup('--sem-plugins', '--nome', 'Novo projeto')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(guide.read_bytes(), original)

    def test_tracked_env_blocks_all_writes(self):
        self.git('init', '-q', str(self.target))
        dotenv = self.target / '.env'
        dotenv.write_bytes(b'LOCAL_SENTINEL=not-a-secret\n')
        self.git('-C', str(self.target), 'add', '--', '.env')
        index = (self.target / '.git/index').read_bytes()
        result = self.run_setup('--sem-plugins')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.target / 'CLAUDE.md').exists())
        self.assertEqual(dotenv.read_bytes(), b'LOCAL_SENTINEL=not-a-secret\n')
        self.assertEqual((self.target / '.git/index').read_bytes(), index)
        self.assertNotIn('LOCAL_SENTINEL', result.stdout + result.stderr)

    def check_ignore_case(self, content, initialize=True):
        if initialize:
            self.git('init', '-q', str(self.target))
        ignore = self.target / '.gitignore'
        ignore.write_bytes(content)
        result = self.run_setup('--sem-plugins')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('-C', str(self.target), 'check-ignore', '--no-index', '.env', check=False).returncode, 0)
        first = ignore.read_bytes()
        self.assertTrue(first.startswith(content))
        self.assertEqual(self.run_setup('--sem-plugins').returncode, 0)
        self.assertEqual(ignore.read_bytes(), first)
        self.assertLessEqual(first.splitlines().count(b'/.env'), 1)

    def test_existing_ignore(self):
        self.check_ignore_case(b'node_modules/\n')

    def test_ignore_missing_newline(self):
        self.check_ignore_case(b'node_modules/')

    def test_ignore_negated_env(self):
        self.check_ignore_case(b'.env\n!.env\n')

    def test_nested_project_ignore_and_tracked_env(self):
        self.git('init', '-q', str(self.target))
        self.target = self.target / 'nested'
        self.target.mkdir()
        self.check_ignore_case(b'node_modules/\n', initialize=False)

    def test_env_tracked_in_parent_repo(self):
        self.git('init', '-q', str(self.target))
        self.target = self.target / 'nested'
        self.target.mkdir()
        write(self.target / '.env', 'LOCAL_SENTINEL=not-a-secret\n')
        self.git('-C', str(self.target), 'add', '--', '.env')
        result = self.run_setup('--sem-plugins')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.target / 'CLAUDE.md').exists())

    def test_force_preserves_env_and_ignore(self):
        write(self.target / '.env', 'LOCAL_SENTINEL=not-a-secret\n')
        write(self.target / '.gitignore', 'custom-cache/\n')
        write(self.target / 'CLAUDE.md', 'old guide')
        result = self.run_setup('--sem-plugins', '--force', '--name', 'Project with spaces')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Project with spaces', (self.target / 'CLAUDE.md').read_text(encoding='utf-8'))
        self.assertEqual((self.target / '.env').read_bytes(), b'LOCAL_SENTINEL=not-a-secret\n')
        self.assertTrue((self.target / '.gitignore').read_bytes().startswith(b'custom-cache/\n'))
        self.assertNotIn('LOCAL_SENTINEL', result.stdout + result.stderr)

    def test_new_project_then_git_ignores_env(self):
        result = self.run_setup('--sem-plugins', '--name', 'New project')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.target / '.git').exists())
        for rel in FILES[1:10]:
            self.assertTrue((self.target / rel).is_file(), rel)
        self.assertIn('New project', (self.target / 'AGENTS.md').read_text(encoding='utf-8'))
        self.git('init', '-q', str(self.target))
        self.assertEqual(self.git('-C', str(self.target), 'check-ignore', '.env', check=False).returncode, 0)

    def test_checkout_failure_can_retry(self):
        skill = self.home / '.claude/skills/humanizer'
        result = self.run_setup('--sem-plugins', env={'TEST_FAIL_CHECKOUT': '1'})
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(skill.exists())
        self.assertEqual(list(skill.parent.glob('.humanizer.*')), [])
        result = self.run_setup('--sem-plugins')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.git('-C', str(skill), 'rev-parse', 'HEAD').stdout.strip(), self.expected_commit)

    def test_existing_skill_wrong_revision_is_preserved(self):
        skill = self.home / '.claude/skills/humanizer'
        self.git('clone', '-q', str(self.upstream), str(skill))
        write(skill / 'SKILL.md', '# Changed revision\n')
        self.git('-C', str(skill), 'add', 'SKILL.md')
        self.git('-C', str(skill), '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid',
                 'commit', '-qm', 'second revision')
        head = self.git('-C', str(skill), 'rev-parse', 'HEAD').stdout
        self.assert_no_project_writes(self.run_setup('--sem-plugins'))
        self.assertEqual(self.git('-C', str(skill), 'rev-parse', 'HEAD').stdout, head)

    def test_existing_skill_dirty_is_preserved(self):
        skill = self.home / '.claude/skills/humanizer'
        self.git('clone', '-q', str(self.upstream), str(skill))
        write(skill / 'notes.txt', 'keep notes')
        self.assert_no_project_writes(self.run_setup('--sem-plugins'))
        self.assertEqual((skill / 'notes.txt').read_text(), 'keep notes')

    def test_existing_skill_cannot_inherit_parent_git(self):
        parent = self.home / '.claude/skills'
        self.git('clone', '-q', str(self.upstream), str(parent))
        write(parent / 'humanizer/SKILL.md', '# nested directory\n')
        self.assert_no_project_writes(self.run_setup('--sem-plugins'))

    def test_plugin_failures_are_nonzero(self):
        for stage in ('marketplace', 'install'):
            with self.subTest(stage=stage):
                result = self.run_setup(env={'TEST_CLAUDE_FAIL_STAGE': stage})
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('Pronto.', result.stdout)

    def test_plugins_skipped_explicitly(self):
        result = self.run_setup('--sem-plugins')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--sem-plugins', result.stdout)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertFalse(any(call[0] == 'claude' for call in calls))

    def test_plugins_skipped_without_claude(self):
        (self.bin / 'claude').unlink()
        result = self.run_setup()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('missing from PATH', result.stdout)
        self.assertFalse(any(json.loads(line)[0] == 'claude' for line in self.calls.read_text().splitlines()))

    def test_full_install_and_repeat(self):
        result = self.run_setup('--name', 'Complete project')
        self.assertEqual(result.returncode, 0, result.stderr)
        for rel in ('scripts/documents.py', 'scripts/docling_worker.py', 'scripts/source_fetch.py',
                    'requirements/docling.txt', 'requirements/docling-media.txt'):
            self.assertEqual((self.target / rel).read_bytes(), (ROOT / rel).read_bytes())
        paths = set(self.target.rglob('*'))
        diagnostic = subprocess.run([sys.executable, str(self.target / 'scripts/documents.py'),
                                     '--root', str(self.target), 'doctor', '--json'],
                                    capture_output=True, timeout=30)
        self.assertEqual(json.loads(diagnostic.stdout)['warnings'], ['runtime_missing'])
        self.assertEqual(set(self.target.rglob('*')), paths)
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        installs = [call[-1] for call in calls if call[:3] == ['claude', 'plugin', 'install']]
        self.assertEqual(len(installs), 5)
        self.assertTrue(all(not any(c.isspace() for c in value) for value in installs))
        before = {rel: (self.target / rel).read_bytes() for rel in FILES[1:10]}
        self.assertEqual(self.run_setup('--name', 'Different name').returncode, 0)
        self.assertEqual(before, {rel: (self.target / rel).read_bytes() for rel in before})

    def test_source_syntax(self):
        subprocess.run([self.bash, '-n', shell_path(self.source / 'setup.sh')], check=True)
        for rel in ('skills-lock.json', '.mcp.json', '.claude/settings.json', '.codex/hooks.json'):
            json.loads((self.source / rel).read_text(encoding='utf-8'))
        codex = tomllib.loads((self.source / '.codex/config.toml').read_text(encoding='utf-8'))
        claude = json.loads((self.source / '.mcp.json').read_text(encoding='utf-8'))
        self.assertEqual({k: v['url'] for k, v in codex['mcp_servers'].items()},
                         {k: v['url'] for k, v in claude['mcpServers'].items()})
        self.assertTrue(all(v['enabled'] is False for v in codex['mcp_servers'].values()))

    def test_default_supports_both_clients(self):
        result = self.run_setup('--no-plugins')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.target / '.codex/config.toml').is_file())
        for root in (self.home / '.claude/skills', self.target / '.agents/skills'):
            skill = root / 'humanizer'
            self.assertTrue((skill / 'SKILL.md').is_file(), root)
            self.assertEqual(self.git('-C', str(skill), 'rev-parse', 'HEAD').stdout.strip(), self.expected_commit)
            self.assertTrue((root / 'humanizer-ptbr/SKILL.md').is_file())

    def test_integration_vault_and_native_entries(self):
        result = self.run_setup('--no-plugins')
        self.assertEqual(result.returncode, 0, result.stderr)
        for rel in INTEGRATION_FILES:
            self.assertTrue((self.target / rel).is_file(), rel)
        self.git('init', '-q', str(self.target))
        self.assertEqual(self.git('-C', str(self.target), 'check-ignore', '--no-index',
                                 '.agents/skills/integrate-from-docs/SKILL.md', check=False).returncode, 1)
        identity = tomllib.loads((self.target / '.codex/agents/integration-specialist.toml').read_text())
        self.assertEqual(identity['name'], 'integration-specialist')

    def test_personalizer_installed_and_runs_in_consumer(self):
        result = self.run_setup('--no-plugins')
        self.assertEqual(result.returncode, 0, result.stderr)
        for rel in PERSONALIZER_FILES:
            self.assertTrue((self.target / rel).is_file(), rel)
        result = subprocess.run([sys.executable, str(self.target / 'scripts/personalize.py'),
                                 'init', '--mode', 'new', '--run', 'first'], cwd=self.target,
                                capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('product/index.md', (self.target / 'vault/index.md').read_text(encoding='utf-8'))

    def test_missing_personalizer_source_blocks_setup(self):
        (self.source / 'skills/personalizer/references/interview.md').unlink()
        self.assert_no_project_writes(self.run_setup('--no-plugins'))

    def test_vault_check_installed_for_each_client_without_changing_notes(self):
        for client in ('claude', 'codex'):
            with self.subTest(client=client):
                self.target = self.base / ('check-' + client)
                self.target.mkdir()
                result = self.run_setup('--client', client, '--sem-plugins')
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                before = {p.relative_to(self.target): p.read_bytes()
                          for p in self.target.rglob('*') if p.is_file()}
                result = subprocess.run([sys.executable, str(self.target / 'scripts/vault.py'),
                                         'check', '--json'], cwd=self.target, capture_output=True,
                                        encoding='utf-8', timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                self.assertEqual(json.loads(result.stdout)['notes_checked'], 3)
                self.assertEqual(before, {p.relative_to(self.target): p.read_bytes()
                                         for p in self.target.rglob('*') if p.is_file()})

    def test_force_preserves_vault_knowledge(self):
        original = b'# Conhecimento do produto\r\n'
        write(self.target / 'vault/index.md', '')
        (self.target / 'vault/index.md').write_bytes(original)
        result = self.run_setup('--no-plugins', '--force')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.target / 'vault/index.md').read_bytes(), original)

    def test_vault_conflict_blocks_all_setup_writes(self):
        write(self.target / 'vault/integrations', 'existing file')
        self.assert_no_project_writes(self.run_setup('--no-plugins'))

    @unittest.skipUnless(os.name == 'nt', 'Windows junction behavior')
    def test_junction_without_python312_helper_blocks_setup(self):
        outside = self.base / 'junction-destination'
        outside.mkdir()
        subprocess.run(['cmd', '/c', 'mklink', '/J', str(self.target / 'vault'), str(outside)],
                       check=True, capture_output=True)
        write(self.base / 'sitecustomize.py', 'from pathlib import Path\nPath.is_junction = lambda self: False\n')
        result = self.run_setup('--no-plugins', env={'PYTHONPATH': str(self.base)})
        self.assert_no_project_writes(result)
        self.assertEqual(list(outside.iterdir()), [])

    def test_codex_only_does_not_touch_claude(self):
        write(self.home / '.claude', 'not used by Codex')
        result = self.run_setup('--client', 'codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.target / 'AGENTS.md').is_file())
        self.assertTrue((self.target / 'CLAUDE.md').is_file())
        self.assertTrue((self.target / '.codex/config.toml').is_file())
        self.assertFalse((self.target / '.claude').exists())
        self.assertFalse((self.target / '.mcp.json').exists())
        self.assertTrue((self.target / '.agents/skills/humanizer/SKILL.md').is_file())
        calls = [json.loads(line) for line in self.calls.read_text().splitlines()]
        self.assertFalse(any(call[0] == 'claude' for call in calls))

    def test_claude_only_does_not_touch_codex(self):
        write(self.target / '.agents', 'not used by Claude')
        result = self.run_setup('--client', 'claude', '--no-plugins')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.target / '.codex').exists())
        self.assertTrue((self.target / '.mcp.json').is_file())
        self.assertTrue((self.home / '.claude/skills/humanizer/SKILL.md').is_file())

    def test_codex_skill_conflict_blocks_all_writes(self):
        skill = self.target / '.agents/skills/humanizer'
        self.git('clone', '-q', str(self.upstream), str(skill))
        write(skill / 'notes.txt', 'preserve')
        self.assert_no_project_writes(self.run_setup('--no-plugins'))
        self.assertFalse((self.home / '.claude/skills/humanizer').exists())

    def test_codex_downloads_are_ignored_in_existing_repo(self):
        self.git('init', '-q', str(self.target))
        write(self.target / '.gitignore', 'custom-cache/\n')
        result = self.run_setup('--client', 'codex')
        self.assertEqual(result.returncode, 0, result.stderr)
        for name in ('humanizer', 'humanizer-ptbr'):
            self.assertEqual(self.git('-C', str(self.target), 'check-ignore', '--no-index',
                                      '.agents/skills/' + name + '/SKILL.md', check=False).returncode, 0)

    def test_existing_codex_config_is_preserved(self):
        path = self.target / '.codex/config.toml'
        write(path, '# Keep my Codex settings\n')
        result = self.run_setup('--no-plugins')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(path.read_text(), '# Keep my Codex settings\n')

    def test_invalid_or_missing_client(self):
        for args in (('--client',), ('--client', 'invalid')):
            result = self.run_setup(*args)
            self.assertEqual(result.returncode, 2)
            self.assert_no_project_writes(result)

    def test_codex_windows_hook_is_safe_and_propagates_failures(self):
        config = json.loads((self.source / '.codex/hooks.json').read_text())
        hook = config['hooks']['PostToolUse'][0]['hooks'][0]
        self.assertIn('commandWindows', hook)
        args = shlex.split(hook['commandWindows'])
        self.assertEqual(args[0], 'python')
        args[0] = sys.executable
        env = self.child_env.copy()
        env.update(HOME=str(self.home), USERPROFILE=str(self.home))
        env['PATH'] = str(Path(self.bash).parent) + os.pathsep + env['PATH']
        self.assertEqual(subprocess.run(args, env=env, timeout=10).returncode, 0)
        write(self.home / '.agents/skills/impeccable/scripts/impeccable', '#!/bin/bash\nexit 23\n')
        self.assertEqual(subprocess.run(args, env=env, timeout=10).returncode, 23)


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--fake-git':
        sys.exit(fake_git(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == '--fake-claude':
        args = sys.argv[2:]
        with open(os.environ['TEST_CALLS'], 'a', encoding='utf-8') as log:
            log.write(json.dumps(['claude', *args]) + '\n')
        stage = 'marketplace' if 'marketplace' in args else 'install'
        sys.exit(19 if os.environ.get('TEST_CLAUDE_FAIL_STAGE') == stage else 0)
    unittest.main()
