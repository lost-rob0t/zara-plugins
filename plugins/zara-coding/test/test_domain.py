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
            branch_inventory = (
                f"feature\t{'b' * 40}\torigin/feature\n"
                f"main\t{'a' * 40}\torigin/main\n"
            )
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
                ): branch_inventory,
                (
                    "for-each-ref",
                    "--count=3",
                    "--sort=refname",
                    "--format=%(refname:short)%09%(objectname)%09%(upstream:short)",
                    "refs/heads/",
                ): branch_inventory,
                ("worktree", "list", "--porcelain", "-z"): (
                    f"worktree {self.repo.resolve()}\x00HEAD {'a' * 40}\x00branch refs/heads/main\x00\x00"
                    f"worktree {self.root / 'wt'}\x00HEAD {'b' * 40}\x00detached\x00locked testing\x00prunable stale\x00\x00"
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
        diff_calls = [
            call
            for call in self.calls
            if call[0][-5:] == ["diff", "--numstat", "--no-renames", "HEAD", "--"]
        ]
        self.assertEqual(len(diff_calls), 2)
        self.assertTrue(all(kwargs["shell"] is False for _, kwargs in diff_calls))

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
        branch_calls = [call for call in self.calls if "for-each-ref" in call[0]]
        self.assertEqual(len(branch_calls), 2)
        self.assertEqual(
            {argument for argv, _ in branch_calls for argument in argv if argument.startswith("--count=")},
            {"--count=2", "--count=3"},
        )
        self.assertTrue(all(argv[-1] == "refs/heads/" for argv, _ in branch_calls))
        self.assertTrue(all(kwargs["shell"] is False for _, kwargs in branch_calls))

    def test_branches_rejects_unbounded_limits_before_spawning_git(self):
        with self.assertRaisesRegex(ValueError, "between 1 and 100"):
            self.inspector.branches(self.repo, limit=0)
        self.assertEqual(self.calls, [])

    def test_create_branch_uses_expected_head_transaction(self):
        self.inspector.create_branch(self.repo, "feature/x", "a" * 40)
        argv, kwargs = self.calls[-1]
        self.assertEqual(argv[-2:], ["update-ref", "--stdin"])
        self.assertEqual(
            kwargs["input"],
            f"start\nverify HEAD {'a' * 40}\ncreate refs/heads/feature/x {'a' * 40}\nprepare\ncommit\n",
        )
        self.assertFalse(kwargs["shell"])

    def test_delete_branch_rejects_checked_out_branch(self):
        with self.assertRaisesRegex(CodingError, "checked out in worktree"):
            self.inspector.delete_branch(self.repo, "main", "a" * 40)

    def test_commit_requires_attached_branch(self):
        def detached_run(argv, **kwargs):
            args = argv[3:]
            if args == ["rev-parse", "--show-toplevel"]:
                output = f"{self.repo.resolve()}\n"
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")
            if args == ["symbolic-ref", "-q", "HEAD"]:
                return subprocess.CompletedProcess(argv, 1, stdout="", stderr="")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        inspector = RepositoryInspector((self.root,), runner=detached_run)
        with self.assertRaisesRegex(CodingError, "attached branch"):
            inspector.commit(self.repo, "message", "a" * 40)

    def test_worktrees_returns_bounded_structured_inventory(self):
        worktrees = self.inspector.worktrees(self.repo, limit=2)
        self.assertEqual(len(worktrees), 2)
        self.assertEqual(worktrees[0]["branch"], "main")
        self.assertFalse(worktrees[0]["detached"])
        self.assertEqual(worktrees[1]["branch"], None)
        self.assertTrue(worktrees[1]["detached"])
        self.assertEqual(worktrees[1]["locked"], "testing")
        self.assertEqual(worktrees[1]["prunable"], "stale")


class PrologRLMBridgeTests(unittest.TestCase):
    def test_status_reports_missing_checkout_without_spawning(self):
        with tempfile.TemporaryDirectory() as temporary:
            bridge = PrologRLMBridge(Path(temporary))
            self.assertEqual(
                bridge.status(),
                {"status": "unavailable", "reason": "prolog-rlm-checkout-missing"},
            )

    def test_status_accepts_ready_facade_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)

            def run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, stdout="ready\t1.2.3\n", stderr="")

            bridge = PrologRLMBridge(checkout, runner=run)
            self.assertEqual(bridge.status(), {"status": "ready", "version": "1.2.3"})

    def test_status_rejects_malformed_ready_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)

            def run(argv, **kwargs):
                return subprocess.CompletedProcess(argv, 0, stdout="ready\n", stderr="")

            bridge = PrologRLMBridge(checkout, runner=run)
            self.assertEqual(
                bridge.status(),
                {"status": "unavailable", "reason": "prolog-rlm-invalid-readiness-output"},
            )

    def test_spec_catalog_calls_prolog_rlm_spec_language(self):
        with tempfile.TemporaryDirectory() as temporary:
            checkout = Path(temporary)
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                return subprocess.CompletedProcess(argv, 0, stdout="ok(catalog)\n", stderr="")

            bridge = PrologRLMBridge(checkout, runner=run)
            result = bridge.spec_catalog()
            self.assertEqual(result, {"status": "ok", "outcome": "ok(catalog)"})
            argv, kwargs = calls[-1]
            self.assertIn("rlm_spec_lang.pl", argv[3])
            self.assertIn("spec_language_catalog", argv[-1])
            self.assertFalse(kwargs["shell"])

    def test_normalize_spec_rejects_unbounded_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            bridge = PrologRLMBridge(Path(temporary), runner=lambda *args, **kwargs: None)
            with self.assertRaisesRegex(CodingError, "65536"):
                bridge.normalize_spec("x" * 65537)


if __name__ == "__main__":
    unittest.main()
