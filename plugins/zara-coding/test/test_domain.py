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
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.email", "test@example.invalid"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "config", "user.name", "Zara Plugin Test"], check=True)
        (self.repo / "tracked.txt").write_text("base\n")
        subprocess.run(["git", "-C", str(self.repo), "add", "tracked.txt"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "commit", "-qm", "initial"], check=True)
        self.inspector = RepositoryInspector((self.root,))

    def tearDown(self):
        self.temporary.cleanup()

    def test_snapshot_is_structured_and_preserves_dirty_evidence(self):
        (self.repo / "tracked.txt").write_text("changed\n")
        snapshot = self.inspector.inspect(self.repo)
        self.assertEqual(snapshot["root"], str(self.repo.resolve()))
        self.assertEqual(len(snapshot["head"]), 40)
        self.assertIsInstance(snapshot["branch"], str)
        self.assertTrue(snapshot["dirty"])
        self.assertIn("tracked.txt", snapshot["changed_paths"])

    def test_rejects_paths_outside_configured_roots(self):
        with self.assertRaisesRegex(CodingError, "outside allowed roots"):
            self.inspector.inspect(Path("/"))

    def test_rejects_non_repository_directory(self):
        plain = self.root / "plain"
        plain.mkdir()
        with self.assertRaisesRegex(CodingError, "Git repository"):
            self.inspector.inspect(plain)


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
