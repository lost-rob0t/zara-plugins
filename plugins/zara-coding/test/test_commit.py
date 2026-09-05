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


class CommitTests(unittest.TestCase):
    def test_domain_commits_only_index_and_cas_updates_current_branch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            parent = "a" * 40
            tree = "b" * 40
            old_tree = "c" * 40
            commit = "d" * 40
            calls = []

            def run(argv, **kwargs):
                calls.append((argv, kwargs))
                args = tuple(argv[3:])
                outputs = {
                    ("rev-parse", "--show-toplevel"): f"{repo.resolve()}\n",
                    ("symbolic-ref", "-q", "HEAD"): "refs/heads/main\n",
                    ("rev-parse", "HEAD"): f"{parent}\n",
                    ("write-tree",): f"{tree}\n",
                    ("rev-parse", f"{parent}^{{tree}}"): f"{old_tree}\n",
                    ("commit-tree", tree, "-p", parent): f"{commit}\n",
                }
                return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(args, ""), stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            evidence = inspector.commit(repo, "bounded commit", parent)

            self.assertEqual(
                evidence,
                {"branch": "main", "parent": parent, "commit": commit, "tree": tree},
            )
            commit_call = next(call for call in calls if call[0][3] == "commit-tree")
            self.assertEqual(commit_call[1]["input"], "bounded commit\n")
            argv_calls = [call[0][3:] for call in calls]
            self.assertIn(["update-ref", "refs/heads/main", commit, parent], argv_calls)
            self.assertNotIn("commit", [argv[0] for argv in argv_calls])
            self.assertTrue(all(call[1]["shell"] is False for call in calls))

    def test_domain_rejects_detached_head_before_writing_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                if args == ("rev-parse", "--show-toplevel"):
                    return subprocess.CompletedProcess(argv, 0, stdout=f"{repo.resolve()}\n", stderr="")
                if args == ("symbolic-ref", "-q", "HEAD"):
                    raise subprocess.CalledProcessError(1, argv)
                if args == ("write-tree",):
                    self.fail("detached HEAD reached write-tree")
                return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "attached branch"):
                inspector.commit(repo, "message", "a" * 40)

    def test_domain_rejects_empty_index_delta(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            parent = "a" * 40
            tree = "b" * 40

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                outputs = {
                    ("rev-parse", "--show-toplevel"): f"{repo.resolve()}\n",
                    ("symbolic-ref", "-q", "HEAD"): "refs/heads/main\n",
                    ("rev-parse", "HEAD"): f"{parent}\n",
                    ("write-tree",): f"{tree}\n",
                    ("rev-parse", f"{parent}^{{tree}}"): f"{tree}\n",
                }
                if args and args[0] == "commit-tree":
                    self.fail("empty index delta reached commit-tree")
                return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(args, ""), stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "no staged changes"):
                inspector.commit(repo, "message", parent)

    def test_domain_rejects_stale_expected_head_before_commit_object(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            expected = "a" * 40
            actual = "b" * 40

            def run(argv, **kwargs):
                args = tuple(argv[3:])
                outputs = {
                    ("rev-parse", "--show-toplevel"): f"{repo.resolve()}\n",
                    ("symbolic-ref", "-q", "HEAD"): "refs/heads/main\n",
                    ("rev-parse", "HEAD"): f"{actual}\n",
                }
                if args == ("write-tree",):
                    self.fail("stale HEAD reached write-tree")
                return subprocess.CompletedProcess(argv, 0, stdout=outputs.get(args, ""), stderr="")

            inspector = RepositoryInspector((root,), runner=run)
            with self.assertRaisesRegex(CodingError, "HEAD changed"):
                inspector.commit(repo, "message", expected)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.RepositoryInspector.commit")
    def test_plugin_commit_requires_canonical_approval(self, commit, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            parent = "a" * 40
            commit.return_value = {"branch": "main", "parent": parent, "commit": "b" * 40, "tree": "c" * 40}
            plugin = ZaraCodingPlugin()
            plugin.start(type("Runtime", (), {"configuration": {"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}})())
            tools = {tool.name: tool for tool in plugin.tools()}
            self.assertTrue(bool((tools["coding.git.commit"].metadata or {}).get("zara_requires_approval", False)))
            evidence = json.loads(plugin.git_commit(str(repo), "bounded commit", parent))
            self.assertEqual(evidence["parent"], parent)
            commit.assert_called_once_with(repo, "bounded commit", parent)


if __name__ == "__main__":
    unittest.main()
