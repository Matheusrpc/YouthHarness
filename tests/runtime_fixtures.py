"""Real prepared missions; only the external client executable is substituted."""
from pathlib import Path
import os
import subprocess
import sys
import uuid
from unittest.mock import patch

from mission_fixtures import MissionCase
import missions

FIXTURE = Path(__file__).parent / 'fixtures/mission_client.py'


class RuntimeCase(MissionCase):
    def git(self, *args, check=True):
        return subprocess.run(['git', '-C', str(self.root), *args], env=self.env,
                              capture_output=True, check=check, timeout=30)

    def setUp(self):
        super().setUp()
        home = str(self.root / 'isolated-home')
        env = patch.dict(os.environ, {'HOME': home, 'USERPROFILE': home})
        env.start()
        self.addCleanup(env.stop)

    def make_manifest(self):
        if not hasattr(self, 'mission'):
            paths = self.tree(pbis=1)
            for path in paths:
                missions.import_item(self.root, path, 0, str(uuid.uuid4()),
                                     dict(id='fixture', role='tech_lead' if '/pbis/' in path else 'pm'))
            config = self.configured()
            for agent in config['agents'].values():
                agent.update(model='latest', capabilities=[])
            missions.apply_config(self.root, config, None)
            request = dict(title='Probe', feature_ids=[self.item_id(p) for p in paths if '/features/' in p],
                           priority=[self.item_id(p) for p in paths if '/pbis/' in p], overrides={},
                           scope_reference='Authorized local fixture')
            self.mission = missions.prepare_mission(self.root, request, str(uuid.uuid4()), dict(id='fixture', role='pm'))
        return dict(schema_version=1, mission_id=self.mission['record_id'], mission_revision=1, role='pm',
                    operation_id=str(uuid.uuid4()), authorization_ref='Local deterministic test',
                    agent_seconds=30, max_runs=1, api_budget_usd=None, fixture_id='echo-v1')

    def fixture_plan(self, plan, mode='success'):
        return dict(plan, argv=[sys.executable, '-I', '-S', str(FIXTURE.resolve()), mode])
