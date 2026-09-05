import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_emacs.client import EmacsClient, EmacsError
from zara_emacs.config import EmacsConfig


class Result:
    def __init__(self, returncode=0, stdout="ok\n", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class Runner:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        return self.results.pop(0)


class EmacsClientTest(unittest.TestCase):
    def client(self, results, **config):
        runner = Runner(results)
        client = EmacsClient(EmacsConfig(projects={"zara": "/work/zara"}, **config), runner=runner)
        return client, runner

    def test_open_file_uses_argv_not_shell_and_returns_ack(self):
        client, runner = self.client([Result(stdout="")])
        result = client.open_file("/tmp/note.org")
        argv, kwargs = runner.calls[0]
        self.assertEqual(argv[-1], "/tmp/note.org")
        self.assertFalse(kwargs.get("shell", False))
        self.assertTrue(result["acknowledged"])

    def test_daily_emits_dictation_request_but_never_claims_started(self):
        client, runner = self.client([Result(stdout='"/notes/2026-09-05.org"\n')])
        result = client.open_daily("2026-09-05")
        self.assertTrue(result["acknowledged"])
        self.assertEqual(result["post_open"], {"request": "dictation", "started": False})
        expression = runner.calls[0][0][-1]
        self.assertIn("org-roam-dailies-goto-date", expression)
        self.assertNotIn("start-process-shell-command", expression)

    def test_magit_resolves_only_known_project_alias(self):
        client, runner = self.client([Result(stdout='t\n')])
        result = client.open_magit("zara")
        self.assertEqual(result["project_id"], "zara")
        self.assertIn(json.dumps("/work/zara"), runner.calls[0][0][-1])
        with self.assertRaisesRegex(EmacsError, "unknown project"):
            client.open_magit("$(touch /tmp/pwned)")
        self.assertEqual(len(runner.calls), 1)

    def test_server_failure_is_explicit_and_bounded(self):
        client, _ = self.client([Result(returncode=1, stderr="server unavailable")])
        with self.assertRaisesRegex(EmacsError, "server unavailable"):
            client.open_scratch()


if __name__ == "__main__":
    unittest.main()
