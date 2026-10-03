import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
FIXTURE = Path(__file__).parent / 'fixtures/mission_client.py'


class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('mission_process'), 'supervisor not implemented')
        self.module = importlib.import_module('mission_process')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def plan(self, mode):
        return dict(argv=[sys.executable, '-I', '-S', str(FIXTURE.resolve()), mode], cwd=str(self.root),
                    stdin=b'', timeout_seconds=5, output_limit_bytes=4096,
                    client='codex', connection='authenticated', credential_env=None)

    def test_timeout_reaps_owned_child_only(self):
        stranger = subprocess.Popen([sys.executable, '-I', '-S', str(FIXTURE.resolve()), 'hang'])
        try:
            result = self.module.supervise(self.plan('child'), on_started=lambda owner: None, stop_requested=lambda: False)
            self.assertEqual(result['reason'], 'timeout')
            self.assertTrue(result['tree_reaped'])
            self.assertTrue((self.root / 'child.pid').exists())
            self.assertIsNone(stranger.poll())
            self.assertTrue(self.module.owner_gone(result['owner']))
        finally:
            stranger.terminate()
            stranger.wait(timeout=5)

    def test_output_limit_is_bounded_and_reaped(self):
        result = self.module.supervise(self.plan('flood'), on_started=lambda _: None, stop_requested=lambda: False)
        self.assertEqual(result['reason'], 'output_limit')
        self.assertLessEqual(len(result['stdout']), 4096)
        self.assertTrue(result['tree_reaped'])

    def test_spawn_failure_is_sanitized_before_effect(self):
        plan = self.plan('success')
        plan['argv'] = [str(self.root / 'missing-private-executable')]
        result = self.module.supervise(plan, on_started=lambda _: None, stop_requested=lambda: False)
        self.assertFalse(result['effect_started'])
        self.assertEqual(result['reason'], 'spawn_failed')
        self.assertNotIn('missing-private', repr(result))

    def test_callback_failure_never_dispatches(self):
        def abort(_):
            raise RuntimeError('simulated coordinator persistence failure')
        with self.assertRaises(RuntimeError):
            self.module.supervise(self.plan('child'), on_started=abort, stop_requested=lambda: False)
        self.assertFalse((self.root / 'child.pid').exists())

    def test_unproven_process_identity_is_never_assumed_dead(self):
        self.assertFalse(self.module.owner_gone({'pid': os.getpid()}))
        self.assertFalse(self.module.process_missing(os.getpid()))
        child = subprocess.Popen([sys.executable, '-I', '-S', '-c', 'pass'])
        child.wait(timeout=20)
        self.assertTrue(self.module.process_missing(child.pid))

    @unittest.skipIf(os.name == 'nt', 'Linux seccomp boundary')
    def test_child_cannot_escape_process_group(self):
        result = self.module.supervise(self.plan('escape'), on_started=lambda _: None, stop_requested=lambda: False)
        self.assertIn(b'escape_refused', result['stdout'])
        self.assertTrue(result['tree_reaped'])
