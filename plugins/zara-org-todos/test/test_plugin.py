import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_org_todos_service.plugin import GIT_DISABLED_MESSAGE, ZaraOrgTodosPlugin
from zara_org_todos_service.sync import SyncResult


class FakeRuntime:
    def __init__(self, configuration):
        self.configuration = configuration
        self.worker = None

    def start_worker(self, name, target):
        self.worker = (name, target)
        return object()


class FakeRunner:
    def __init__(self, config):
        self.config = config
        self.calls = 0
        self.saved_file = None

    def run(self, *, saved_file=None):
        self.calls += 1
        self.saved_file = saved_file
        return SyncResult(0, "synced\n", "", 0.1)


class ZaraOrgTodosPluginTest(unittest.TestCase):
    def test_org_only_default_registers_no_sync_worker(self):
        runtime = FakeRuntime({})
        with patch("zara_org_todos_service.plugin.SyncRunner", FakeRunner):
            plugin = ZaraOrgTodosPlugin()
            plugin.start(runtime)
        self.assertIsNone(runtime.worker)
        self.assertIsNone(plugin._runner)
        status = json.loads(plugin.status())
        self.assertEqual(status["backend"], "org-mode")
        self.assertFalse(status["git_sync"])
        self.assertFalse(status["auto_sync"])
        self.assertNotIn("remote", status)

    def test_start_registers_worker_when_git_auto_sync_enabled(self):
        runtime = FakeRuntime(
            {
                "git_sync": True,
                "remote": "ssh://git.example/user/tasks.git",
                "auto_sync": True,
                "interval_seconds": 60,
            }
        )
        with patch("zara_org_todos_service.plugin.SyncRunner", FakeRunner):
            plugin = ZaraOrgTodosPlugin()
            plugin.start(runtime)
        self.assertEqual(runtime.worker[0], "sync")
        status = json.loads(plugin.status())
        self.assertTrue(status["git_sync"])
        self.assertTrue(status["auto_sync"])
        self.assertEqual(status["remote"], "ssh://git.example/user/tasks.git")

    def test_manual_sync_reports_disabled_in_org_only_mode(self):
        runtime = FakeRuntime({})
        with patch("zara_org_todos_service.plugin.SyncRunner", FakeRunner):
            plugin = ZaraOrgTodosPlugin()
            plugin.start(runtime)
        self.assertEqual(plugin.sync_now(), GIT_DISABLED_MESSAGE)

    def test_manual_sync_updates_status_when_git_enabled(self):
        runtime = FakeRuntime(
            {
                "git_sync": True,
                "remote": "ssh://git.example/user/tasks.git",
                "auto_sync": False,
            }
        )
        with patch("zara_org_todos_service.plugin.SyncRunner", FakeRunner):
            plugin = ZaraOrgTodosPlugin()
            plugin.start(runtime)
            self.assertEqual(plugin.sync_now(), "synced")
        status = json.loads(plugin.status())
        self.assertEqual(status["last_returncode"], 0)
        self.assertEqual(status["last_summary"], "synced")

    def test_org_mutation_never_touches_git_by_default(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime({"org_dir": directory})
            with patch("zara_org_todos_service.plugin.SyncRunner", FakeRunner):
                plugin = ZaraOrgTodosPlugin()
                plugin.start(runtime)
                result = plugin.add_todo("Ship Org plugin")
            self.assertIn("[TODO] Ship Org plugin", result)
            self.assertIsNone(plugin._runner)
            self.assertTrue((Path(directory) / "inbox.org").is_file())

    def test_org_mutation_syncs_before_and_after_when_git_enabled(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime(
                {
                    "git_sync": True,
                    "remote": "ssh://git.example/user/tasks.git",
                    "auto_sync": False,
                    "org_dir": directory,
                }
            )
            with patch("zara_org_todos_service.plugin.SyncRunner", FakeRunner):
                plugin = ZaraOrgTodosPlugin()
                plugin.start(runtime)
                result = plugin.add_todo("Ship Org plugin")
            self.assertIn("[TODO] Ship Org plugin", result)
            self.assertEqual(plugin._runner.calls, 2)
            self.assertEqual(plugin._runner.saved_file, Path(directory) / "inbox.org")
