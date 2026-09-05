import json
import sys
import tempfile
import types
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))


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

from zara_coding.plugin import ZaraCodingPlugin, create_plugin


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration


class FakePrologRLM:
    def status(self):
        return {"status": "ready", "version": "test"}

    def spec_catalog(self):
        return {"status": "ok", "outcome": "ok(spec_language_catalog{assertions:[]})"}

    def normalize_spec(self, source):
        return {"status": "ok", "outcome": f"ok(normalized({source!r}))"}


class CodingPluginTests(unittest.TestCase):
    def test_factory_metadata_matches_registry_contract(self):
        plugin = create_plugin()
        self.assertEqual(plugin.metadata.name, "zara-coding")
        self.assertEqual(plugin.metadata.version, "0.1.0")
        self.assertEqual(plugin.metadata.api_version, "1")

    def test_tool_surface_requires_approval_only_for_mutation(self):
        tools = {tool.name: tool for tool in ZaraCodingPlugin().tools()}
        self.assertEqual(
            set(tools),
            {
                "coding.status",
                "coding.repo.list",
                "coding.repo.status",
                "coding.repo.inspect",
                "coding.git.diff",
                "coding.git.log",
                "coding.git.branches",
                "coding.git.branch.create",
                "coding.git.worktree.list",
                "coding.spec.catalog",
                "coding.spec.normalize",
            },
        )
        self.assertTrue(bool((tools["coding.git.branch.create"].metadata or {}).get("zara_requires_approval", False)))
        for name, tool in tools.items():
            if name == "coding.git.branch.create":
                continue
            self.assertFalse(bool((tool.metadata or {}).get("zara_requires_approval", False)))

    def test_unconfigured_plugin_loads_degraded_and_fails_repo_inspection_closed(self):
        plugin = ZaraCodingPlugin()
        plugin.start(Runtime({"plugins": {"zara-coding": {}}}))
        status = json.loads(plugin.status())
        self.assertEqual(status["status"], "degraded")
        self.assertEqual(status["repository"], {"status": "unavailable", "reason": "allowed-roots-not-configured"})
        self.assertEqual(status["prolog_rlm"], {"status": "unavailable", "reason": "prolog-rlm-checkout-not-configured"})
        with self.assertRaisesRegex(RuntimeError, "allowed-roots-not-configured"):
            plugin.list_repositories()
        with self.assertRaisesRegex(RuntimeError, "allowed-roots-not-configured"):
            plugin.repo_status("/")
        with self.assertRaisesRegex(RuntimeError, "allowed-roots-not-configured"):
            plugin.inspect_repo("/")
        with self.assertRaisesRegex(RuntimeError, "allowed-roots-not-configured"):
            plugin.git_diff("/")
        with self.assertRaisesRegex(RuntimeError, "allowed-roots-not-configured"):
            plugin.git_log("/")
        with self.assertRaisesRegex(RuntimeError, "allowed-roots-not-configured"):
            plugin.git_branches("/")
        with self.assertRaisesRegex(RuntimeError, "allowed-roots-not-configured"):
            plugin.git_branch_create("/", "feature")
        with self.assertRaisesRegex(RuntimeError, "allowed-roots-not-configured"):
            plugin.git_worktrees("/")
        with self.assertRaisesRegex(RuntimeError, "Prolog-RLM"):
            plugin.spec_catalog()
        with self.assertRaisesRegex(RuntimeError, "Prolog-RLM"):
            plugin.normalize_spec("spec([]).")

    def test_spec_catalog_returns_canonical_prolog_rlm_outcome_as_structured_json(self):
        plugin = ZaraCodingPlugin()
        plugin.prolog_rlm = FakePrologRLM()
        evidence = json.loads(plugin.spec_catalog())
        self.assertEqual(evidence["status"], "ok")
        self.assertIn("assertions:[]", evidence["outcome"])

    def test_spec_normalize_returns_prolog_rlm_outcome_as_structured_json(self):
        plugin = ZaraCodingPlugin()
        plugin.prolog_rlm = FakePrologRLM()
        evidence = json.loads(plugin.normalize_spec("spec([subject(x)])."))
        self.assertEqual(evidence["status"], "ok")
        self.assertIn("normalized", evidence["outcome"])

    @patch("zara_coding.plugin.shutil.which", return_value=None)
    def test_missing_git_degrades_honestly(self, _which):
        with tempfile.TemporaryDirectory() as temporary:
            plugin = ZaraCodingPlugin()
            plugin.start(Runtime({"plugins": {"zara-coding": {"allowed_roots": [temporary]}}}))
            status = json.loads(plugin.status())
            self.assertEqual(status["repository"], {"status": "unavailable", "reason": "git-executable-not-found"})
            with self.assertRaisesRegex(RuntimeError, "git-executable-not-found"):
                plugin.inspect_repo(temporary)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.RepositoryInspector.list_repositories")
    def test_repo_list_returns_bounded_structured_discovery(self, list_repositories, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            list_repositories.return_value = [{"root": str(repo.resolve())}]
            plugin = ZaraCodingPlugin()
            plugin.start(Runtime({"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}))
            evidence = json.loads(plugin.list_repositories(limit=7))
            self.assertEqual(evidence, [{"root": str(repo.resolve())}])
            list_repositories.assert_called_once_with(limit=7)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.RepositoryInspector.inspect")
    def test_repo_status_and_inspect_share_structured_repo_evidence(self, inspect, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            inspect.return_value = {
                "root": str(repo.resolve()),
                "head": "b" * 40,
                "branch": "main",
                "dirty": False,
                "changed_paths": [],
            }
            plugin = ZaraCodingPlugin()
            plugin.start(Runtime({"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}))
            status = json.loads(plugin.repo_status(str(repo)))
            evidence = json.loads(plugin.inspect_repo(str(repo)))
            self.assertEqual(status, evidence)
            self.assertEqual(status["head"], "b" * 40)
            self.assertEqual(inspect.call_count, 2)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.RepositoryInspector.diff")
    def test_git_diff_returns_structured_summary_with_explicit_bound(self, diff, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            diff.return_value = [{"path": "file.py", "additions": 4, "deletions": 2, "binary": False}]
            plugin = ZaraCodingPlugin()
            plugin.start(Runtime({"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}))
            evidence = json.loads(plugin.git_diff(str(repo), max_files=7))
            self.assertEqual(evidence[0]["path"], "file.py")
            diff.assert_called_once_with(repo, max_files=7)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.RepositoryInspector.log")
    def test_git_log_returns_structured_history_with_explicit_bound(self, log, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            log.return_value = [{"commit": "c" * 40, "parents": [], "subject": "initial"}]
            plugin = ZaraCodingPlugin()
            plugin.start(Runtime({"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}))
            evidence = json.loads(plugin.git_log(str(repo), limit=7))
            self.assertEqual(evidence[0]["commit"], "c" * 40)
            log.assert_called_once_with(repo, limit=7)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.RepositoryInspector.branches")
    def test_git_branches_returns_structured_local_inventory_with_explicit_bound(self, branches, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            branches.return_value = [{"name": "main", "commit": "d" * 40, "upstream": "origin/main"}]
            plugin = ZaraCodingPlugin()
            plugin.start(Runtime({"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}))
            evidence = json.loads(plugin.git_branches(str(repo), limit=9))
            self.assertEqual(evidence[0]["name"], "main")
            branches.assert_called_once_with(repo, limit=9)

    @patch("zara_coding.plugin.shutil.which", return_value="/usr/bin/git")
    @patch("zara_coding.plugin.RepositoryInspector.worktrees")
    def test_git_worktree_list_returns_structured_inventory_with_explicit_bound(self, worktrees, _which):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            worktrees.return_value = [{"path": str(repo), "head": "e" * 40, "branch": "main", "detached": False}]
            plugin = ZaraCodingPlugin()
            plugin.start(Runtime({"plugins": {"zara-coding": {"allowed_roots": [str(root)]}}}))
            evidence = json.loads(plugin.git_worktrees(str(repo), limit=6))
            self.assertEqual(evidence[0]["branch"], "main")
            worktrees.assert_called_once_with(repo, limit=6)


if __name__ == "__main__":
    unittest.main()
