import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_org_todos_service.plugin import ZaraOrgTodosPlugin
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
    def test_start_registers_worker_when_auto_sync_enabled(self):
        runtime = FakeRuntime({"interval_seconds": 60})
        with patch("zara_org_todos_service.plugin.SyncRunner", FakeRunner):
            plugin = ZaraOrgTodosPlugin()
            plugin.start(runtime)
        self.assertEqual(runtime.worker[0], "sync")
        status = json.loads(plugin.status())
        self.assertEqual(status["backend"], "org-mode")
        self.assertTrue(status["auto_sync"])

    def test_start_does_not_register_worker_when_disabled(self):
        runtime = FakeRuntime({"auto_sync": False})
        with patch("zara_org_todos_service.plugin.SyncRunner", FakeRunner):
            plugin = ZaraOrgTodosPlugin()
            plugin.start(runtime)
        self.assertIsNone(runtime.worker)

    def test_manual_sync_updates_status(self):
        runtime = FakeRuntime({"auto_sync": False})
        with patch("zara_org_todos_service.plugin.SyncRunner", FakeRunner):
            plugin = ZaraOrgTodosPlugin()
            plugin.start(runtime)
            self.assertEqual(plugin.sync_now(), "synced")
        status = json.loads(plugin.status())
        self.assertEqual(status["last_returncode"], 0)
        self.assertEqual(status["last_summary"], "synced")

    def test_org_mutation_syncs_changed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            runtime = FakeRuntime({"auto_sync": False, "org_dir": directory})
            with patch("zara_org_todos_service.plugin.SyncRunner", FakeRunner):
                plugin = ZaraOrgTodosPlugin()
                plugin.start(runtime)
                result = plugin.add_todo("Ship Org plugin")
            self.assertIn("[TODO] Ship Org plugin", result)
            self.assertEqual(plugin._runner.calls, 1)
            self.assertEqual(plugin._runner.saved_file, Path(directory) / "inbox.org")
