import json
import subprocess
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError, RepositoryInspector


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str = ""
    api_version: str = "1"
    description: str = ""


class ServicePlugin:
    pass


zara = types.ModuleType("zara")
zara_plugins = types.ModuleType("zara.plugins")
zara_plugins.PluginMetadata = PluginMetadata
zara_plugins.ServicePlugin = ServicePlugin
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", zara_plugins)

from zara_coding.plugin import ZaraCodingPlugin


class BranchDeleteTests(unittest.TestCase):
    def test_domain_deletes_only_expected_unchecked_out_branch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            expected = "a" * 40
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    output = f"{repo.resolve()}\n"
                elif args == ("worktree", "list", "--porcelain", "-z"):
                    output = f"worktree {repo.resolve()}\0HEAD {'b' * 40}\0branch refs/heads/main\0\0"
                else:
                    output = ""
                return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            evidence = inspector.delete_branch(repo, "feature/safe", expected)

            self.assertEqual(evidence, {"branch": "feature/safe", "deleted_head": expected})
            argv_calls = [call[0][3:] for call in calls]
            self.assertIn(["check-ref-format", "refs/heads/feature/safe"], argv_calls)
            self.assertIn(["update-ref", "-d", "refs/heads/feature/safe", expected], argv_calls)
            self.assertTrue(all(call[1]["shell"] is False for call in calls))

    def test_domain_rejects_deleting_branch_checked_out_in_any_worktree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            expected = "a" * 40

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    return subprocess.CompletedProcess(argv, 0, stdout=f"{repo.resolve()}\n", stderr="")
                if args == ("worktree", "list", "--porcelain", "-z"):
                    output = f"worktree {repo.resolve()}\0HEAD {expected}\0branch refs/heads/feature/safe\0\0"
                    return subprocess.CompletedProcess(argv, 0, stdout=output, stderr="")
                if args and args[0] == "update-ref":
                    self.fail("checked-out branch reached deletion")
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "checked out"):
                inspector.delete_branch(repo, "feature/safe", expected)

    def test_domain_requires_full_expected_commit_oid(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            inspector = RepositoryInspector((root,), runner=lambda *_args, **_kwargs: None)
            for value in ("", "HEAD", "abc123", "a" * 39, "g" * 40):
                with self.subTest(value=value):
                    with self.assertRaisesRegex(ValueError, "expected_head"):
                        inspector.delete_branch(repo, "feature/safe", value)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.RepositoryInspector.delete_branch")
    def test_plugin_branch_delete_requires_canonical_approval(self, delete_branch, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            expected = "c" * 40
            delete_branch.return_value = {"branch": "feature/safe", "deleted_head": expected}
            plugin = ZaraCodingPlugin()
            plugin.start(type("Runtime", (), {"configuration": {"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}})())
            tools = {tool.name: tool for tool in plugin.tools()}
            self.assertTrue(bool((tools["coding.git.branch.delete"].metadata or {}).get("zara_requires_approval", False)))
            evidence = json.loads(plugin.git_branch_delete(str(repo), "feature/safe", expected))
            self.assertEqual(evidence["deleted_head"], expected)
            delete_branch.assert_called_once_with(repo, "feature/safe", expected)


if __name__ == "__main__":
    unittest.main()
