import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_org_todos_service.config import OrgTodosConfig
from zara_org_todos_service.sync import SyncBusyError, SyncError, SyncRunner


class SyncRunnerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.script = root / "gpt-todos-sync"
        self.script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        self.config = OrgTodosConfig(
            repo_dir=root / "repo",
            org_dir=root / "org",
            remote="ssh://example/repo",
            interval_seconds=300,
            auto_sync=True,
            timeout_seconds=30,
        )

    def test_runs_bundled_script_with_expected_environment(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            captured["kwargs"] = kwargs
            return subprocess.CompletedProcess(command, 0, "synced\n", "")

        runner = SyncRunner(self.config, script_path=self.script, run_process=fake_run)
        result = runner.run()
        self.assertEqual(captured["command"], ["bash", str(self.script)])
        env = captured["kwargs"]["env"]
        self.assertEqual(env["GPT_TODOS_REPO_DIR"], str(self.config.repo_dir))
        self.assertEqual(env["GPT_TODOS_ORG_DIR"], str(self.config.org_dir))
        self.assertEqual(env["GPT_TODOS_REMOTE"], self.config.remote)
        self.assertNotEqual(env["DOTFILES_DIR"], os.path.expanduser("~/.dotfiles"))
        self.assertEqual(result.summary, "synced")

    def test_file_mode_is_passed_without_shell_interpolation(self):
        captured = {}

        def fake_run(command, **kwargs):
            captured["command"] = command
            return subprocess.CompletedProcess(command, 0, "", "")

        saved = self.config.org_dir / "weekly file.org"
        runner = SyncRunner(self.config, script_path=self.script, run_process=fake_run)
        runner.run(saved_file=saved)
        self.assertEqual(captured["command"], ["bash", str(self.script), "--file", str(saved)])

    def test_nonzero_exit_is_explicit_failure(self):
        def fake_run(command, **kwargs):
            return subprocess.CompletedProcess(command, 5, "", "concurrent local/remote edit conflict")

        runner = SyncRunner(self.config, script_path=self.script, run_process=fake_run)
        with self.assertRaisesRegex(SyncError, "concurrent local/remote edit conflict"):
            runner.run()

    def test_concurrent_sync_is_rejected(self):
        entered = threading.Event()
        release = threading.Event()

        def slow_run(command, **kwargs):
            entered.set()
            release.wait(2)
            return subprocess.CompletedProcess(command, 0, "", "")

        runner = SyncRunner(self.config, script_path=self.script, run_process=slow_run)
        thread = threading.Thread(target=runner.run)
        thread.start()
        self.assertTrue(entered.wait(1))
        try:
            with self.assertRaises(SyncBusyError):
                runner.run()
        finally:
            release.set()
            thread.join(2)
