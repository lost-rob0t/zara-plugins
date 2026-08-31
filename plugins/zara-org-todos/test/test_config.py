import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))

from zara_org_todos_service.config import OrgTodosConfig


class OrgTodosConfigTest(unittest.TestCase):
    def test_defaults_match_gpt_todos_workflow(self):
        with patch.dict(os.environ, {}, clear=True), patch('pathlib.Path.home', return_value=Path('/home/test')):
            cfg = OrgTodosConfig.from_mapping({})
        self.assertEqual(cfg.repo_dir, Path('/home/test/Documents/gpt-todos'))
        self.assertEqual(cfg.org_dir, Path('/home/test/Documents/Notes/org/agenda'))
        self.assertEqual(cfg.remote, 'git@github.com:lost-rob0t/gpt-todos.git')
        self.assertEqual(cfg.interval_seconds, 300)
        self.assertTrue(cfg.auto_sync)

    def test_mapping_and_environment_override(self):
        env = {
            'ZARA_ORG_TODOS_REPO_DIR': '/tmp/repo',
            'ZARA_ORG_TODOS_INTERVAL': '90',
            'ZARA_ORG_TODOS_AUTO_SYNC': 'false',
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = OrgTodosConfig.from_mapping({'org_dir': '/tmp/org', 'remote': 'ssh://example/repo'})
        self.assertEqual(cfg.repo_dir, Path('/tmp/repo'))
        self.assertEqual(cfg.org_dir, Path('/tmp/org'))
        self.assertEqual(cfg.remote, 'ssh://example/repo')
        self.assertEqual(cfg.interval_seconds, 90)
        self.assertFalse(cfg.auto_sync)

    def test_interval_below_minimum_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'at least 60'):
            OrgTodosConfig.from_mapping({'interval_seconds': 10})
