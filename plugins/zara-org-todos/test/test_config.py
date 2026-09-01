import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_org_todos_service.config import OrgTodosConfig


class OrgTodosConfigTest(unittest.TestCase):
    def test_defaults_are_org_only(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "pathlib.Path.home", return_value=Path("/home/test")
        ):
            cfg = OrgTodosConfig.from_mapping({})
        self.assertEqual(cfg.org_dir, Path("/home/test/Documents/Notes/org/agenda"))
        self.assertEqual(
            cfg.repo_dir,
            Path("/home/test/.local/share/zarathushtra/org-todos-git"),
        )
        self.assertIsNone(cfg.remote)
        self.assertFalse(cfg.git_sync)
        self.assertFalse(cfg.auto_sync)
        self.assertEqual(cfg.interval_seconds, 300)

    def test_git_sync_uses_generic_user_remote(self):
        env = {
            "ZARA_ORG_TODOS_REPO_DIR": "/tmp/repo",
            "ZARA_ORG_TODOS_GIT_SYNC": "true",
            "ZARA_ORG_TODOS_REMOTE": "ssh://git.example/user/tasks.git",
            "ZARA_ORG_TODOS_INTERVAL": "90",
            "ZARA_ORG_TODOS_AUTO_SYNC": "true",
        }
        with patch.dict(os.environ, env, clear=True):
            cfg = OrgTodosConfig.from_mapping({"org_dir": "/tmp/org"})
        self.assertEqual(cfg.repo_dir, Path("/tmp/repo"))
        self.assertEqual(cfg.org_dir, Path("/tmp/org"))
        self.assertEqual(cfg.remote, "ssh://git.example/user/tasks.git")
        self.assertTrue(cfg.git_sync)
        self.assertTrue(cfg.auto_sync)
        self.assertEqual(cfg.interval_seconds, 90)

    def test_git_sync_requires_explicit_remote(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(
            ValueError, "remote is required"
        ):
            OrgTodosConfig.from_mapping({"git_sync": True})

    def test_auto_sync_requires_git_sync(self):
        with self.assertRaisesRegex(ValueError, "requires git_sync"):
            OrgTodosConfig.from_mapping({"auto_sync": True})

    def test_interval_below_minimum_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "at least 60"):
            OrgTodosConfig.from_mapping({"interval_seconds": 10})
