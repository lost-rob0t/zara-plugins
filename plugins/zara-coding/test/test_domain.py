import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, PrologRLMBridge, RepositoryInspector


class RepositoryInspectorTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.repo = self.root / "repo"
        self.repo.mkdir()
        self.plain = self.root / "plain"
        self.plain.mkdir()
        self.calls = []

        def run(argv, **kwargs):
            self.calls.append((argv, kwargs))
            cwd = Path(argv[2])
            args = argv[3:]
            if cwd == self.plain and args[:2] == ["rev-parse", "--show-toplevel"]:
                raise subprocess.CalledProcessError(128, argv)
            outputs = {
                ("rev-parse", "--show-toplevel"): f"{self.repo.resolve()}\n",
                ("rev-parse", "HEAD"): "a" * 40 + "\n",
                ("symbolic-ref", "--short", "-q", "HEAD"): "main\n",
                ("diff", "--name-only", "HEAD"): "tracked.txt\n",
                ("ls-files", "--others", "--exclude-standard"): "new.txt\n",
            }
            return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(tuple(args), ""), stderr="")

        self.inspector = RepositoryInspector((self.root,), runner=run)

    def tearDown(self):
        self.temporary.cleanup()

    def test_snapshot_is_structured_and_preserves_dirty_evidence(self):
        snapshot = self.inspector.inspect(self.repo)
        self.assertEqual(snapshot["root"], str(self.repo.resolve()))
        self.assertEqual(snapshot["head"], "a" * 40)
        self.assertEqual(snapshot["branch"], "main")
        self.assertTrue(snapshot["dirty"])
        self.assertEqual(snapshot["changed_paths"], ["new.txt", "tracked.txt"])
        self.assertTrue(all(call[0][0] == "git" for call in self.calls))
        self.assertTrue(all(call[1]["shell"] is False for call in self.calls))

    def test_rejects_paths_outside_configured_roots(self):
        with self.assertRaisesRegex(CodingError, "outside allowed roots"):
            self.inspector.inspect(Path("/"))
        self.assertEqual(self.calls, [])

    def test_rejects_non_repository_directory(self):
        with self.assertRaisesRegex(CodingError, "Git repository"):
            self.inspector.inspect(self.plain)


class PrologRLMBridgeTests(unittest.TestCase):
    def test_readiness_uses_public_rlm_facade_without_shell_interpolation(self):
        checkout = Path("/srv/prolog-rlm")
        calls = []

        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            return subprocess.CompletedProcess(argv, 0, stdout="ready\t0.9.0\n", stderr="")

        bridge = PrologRLMBridge(checkout, executable="swipl", runner=run)
        status = bridge.status()
        self.assertEqual(status, {"status": "ready", "version": "0.9.0"})
        argv, kwargs = calls[0]
        self.assertEqual(argv[0], "swipl")
        self.assertIn(str(checkout / "prolog" / "rlm.pl"), argv)
        self.assertFalse(kwargs.get("shell", False))
        self.assertTrue(kwargs["check"])
        self.assertGreater(kwargs["timeout"], 0)

    def test_missing_checkout_degrades_honestly(self):
        bridge = PrologRLMBridge(Path("/definitely/missing/prolog-rlm"))
        self.assertEqual(
            bridge.status(),
            {"status": "unavailable", "reason": "prolog-rlm-checkout-missing"},
        )

    def test_failed_runtime_reports_bounded_error_without_claiming_ready(self):
        def run(argv, **kwargs):
            raise subprocess.CalledProcessError(2, argv, stderr="boom")

        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            (checkout / "prolog").mkdir()
            (checkout / "prolog" / "rlm.pl").write_text(":- module(rlm, []).\n")
            bridge = PrologRLMBridge(checkout, runner=run)
            status = bridge.status()
        self.assertEqual(status["status"], "unavailable")
        self.assertEqual(status["reason"], "prolog-rlm-not-ready")


if __name__ == "__main__":
    unittest.main()
