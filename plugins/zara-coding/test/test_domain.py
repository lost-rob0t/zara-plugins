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
                ("diff", "--numstat", "--no-renames", "HEAD", "--"): "3\t1\ttracked.txt\n-\t-\tbinary.dat\n",
                ("ls-files", "--others", "--exclude-standard"): "new.txt\n",
                (
                    "log",
                    "--max-count=2",
                    "--format=%H%x09%P%x09%an%x09%aI%x09%s",
                ): (
                    f"{'b' * 40}\t{'a' * 40}\tAlice\t2026-09-05T10:00:00-04:00\tsecond\n"
                    f"{'a' * 40}\t\tBob\t2026-09-04T09:00:00-04:00\tfirst\n"
                ),
                (
                    "for-each-ref",
                    "--count=2",
                    "--sort=refname",
                    "--format=%(refname:short)%09%(objectname)%09%(upstream:short)",
                    "refs/heads/",
                ): (
                    f"feature\t{'b' * 40}\torigin/feature\n"
                    f"main\t{'a' * 40}\torigin/main\n"
                ),
            }
            return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(tuple(args), ""), stderr="")

        self.inspector = RepositoryInspector((self.root,), runner=run)

    def tearDown(self):
        self.temporary.cleanup()

    def test_list_repositories_discovers_only_bounded_immediate_git_roots(self):
        (self.repo / ".git").mkdir()
        second = self.root / "second"
        second.mkdir()
        (second / ".git").write_text("gitdir: /tmp/worktree\n")
        nested = self.plain / "nested"
        nested.mkdir()
        (nested / ".git").mkdir()
        repositories = self.inspector.list_repositories(limit=2)
        self.assertEqual(
            repositories,
            [
                {"root": str(self.repo.resolve())},
                {"root": str(second.resolve())},
            ],
        )
        self.assertEqual(self.calls, [])

    def test_list_repositories_fails_closed_when_discovery_exceeds_bound(self):
        (self.repo / ".git").mkdir()
        second = self.root / "second"
        second.mkdir()
        (second / ".git").mkdir()
        with self.assertRaisesRegex(CodingError, "exceeds repository limit"):
            self.inspector.list_repositories(limit=1)

    def test_list_repositories_rejects_invalid_bound_without_scanning(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            self.inspector.list_repositories(limit=0)

    def test_snapshot_is_structured_and_preserves_dirty_evidence(self):
        snapshot = self.inspector.inspect(self.repo)
        self.assertEqual(snapshot["root"], str(self.repo.resolve()))
        self.assertEqual(snapshot["head"], "a" * 40)
        self.assertEqual(snapshot["branch"], "main")
        self.assertTrue(snapshot["dirty"])
        self.assertEqual(snapshot["changed_paths"], ["new.txt", "tracked.txt"])
        self.assertTrue(all(call[0][0] == "git" for call in self.calls))
        self.assertTrue(all(call[1]["shell"] is False for call in self.calls))

    def test_diff_returns_bounded_structured_numstat_evidence(self):
        diff = self.inspector.diff(self.repo, max_files=2)
        self.assertEqual(
            diff,
            [
                {"path": "tracked.txt", "additions": 3, "deletions": 1, "binary": False},
                {"path": "binary.dat", "additions": None, "deletions": None, "binary": True},
            ],
        )
        argv, kwargs = self.calls[-1]
        self.assertEqual(argv[-5:], ["diff", "--numstat", "--no-renames", "HEAD", "--"])
        self.assertFalse(kwargs["shell"])

    def test_diff_fails_closed_when_changed_file_count_exceeds_bound(self):
        with self.assertRaisesRegex(CodingError, "exceeds file limit"):
            self.inspector.diff(self.repo, max_files=1)

    def test_diff_rejects_invalid_bound_before_spawning_git(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            self.inspector.diff(self.repo, max_files=0)
        self.assertEqual(self.calls, [])

    def test_log_returns_bounded_structured_commit_evidence(self):
        history = self.inspector.log(self.repo, limit=2)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0]["commit"], "b" * 40)
        self.assertEqual(history[0]["parents"], ["a" * 40])
        self.assertEqual(history[0]["author"], "Alice")
        self.assertEqual(history[0]["authored_at"], "2026-09-05T10:00:00-04:00")
        self.assertEqual(history[0]["subject"], "second")
        self.assertEqual(history[1]["parents"], [])
        argv, kwargs = self.calls[-1]
        self.assertIn("--max-count=2", argv)
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 5)

    def test_log_rejects_unbounded_limits_before_spawning_git(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            self.inspector.log(self.repo, limit=101)
        self.assertEqual(self.calls, [])

    def test_branches_returns_bounded_structured_local_refs(self):
        branches = self.inspector.branches(self.repo, limit=2)
        self.assertEqual(
            branches,
            [
                {"name": "feature", "commit": "b" * 40, "upstream": "origin/feature"},
                {"name": "main", "commit": "a" * 40, "upstream": "origin/main"},
            ],
        )
        argv, kwargs = self.calls[-1]
        self.assertIn("--count=2", argv)
        self.assertEqual(argv[-1], "refs/heads/")
        self.assertFalse(kwargs["shell"])

    def test_branches_rejects_unbounded_limits_before_spawning_git(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            self.inspector.branches(self.repo, limit=0)
        self.assertEqual(self.calls, [])

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
