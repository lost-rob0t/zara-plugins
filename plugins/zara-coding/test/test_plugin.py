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

    def normalize_spec(self, source):
        return {"status": "ok", "outcome": f"ok(normalized({source!r}))"}


class CodingPluginTests(unittest.TestCase):
    def test_factory_metadata_matches_registry_contract(self):
        plugin = create_plugin()
        self.assertEqual(plugin.metadata.name, "zara-coding")
        self.assertEqual(plugin.metadata.version, "0.1.0")
        self.assertEqual(plugin.metadata.api_version, "1")

    def test_read_only_initial_surface_has_no_approval_bypass(self):
        tools = {tool.name: tool for tool in ZaraCodingPlugin().tools()}
        self.assertEqual(
            set(tools),
            {"coding.status", "coding.repo.inspect", "coding.git.log", "coding.spec.normalize"},
        )
        for tool in tools.values():
            self.assertFalse(bool((tool.metadata or {}).get("zara_requires_approval", False)))

    def test_unconfigured_plugin_loads_degraded_and_fails_repo_inspection_closed(self):
        plugin = ZaraCodingPlugin()
        plugin.start(Runtime({"plugins": {"zara-coding": {}}}))
        status = json.loads(plugin.status())
        self.assertEqual(status["status"], "degraded")
        self.assertEqual(status["repository"], {"status": "unavailable", "reason": "allowed-roots-not-configured"})
        self.assertEqual(status["prolog_rlm"], {"status": "unavailable", "reason": "prolog-rlm-checkout-not-configured"})
        with self.assertRaisesRegex(RuntimeError, "allowed-roots-not-configured"):
            plugin.inspect_repo("/")
        with self.assertRaisesRegex(RuntimeError, "allowed-roots-not-configured"):
            plugin.git_log("/")
        with self.assertRaisesRegex(RuntimeError, "Prolog-RLM"):
            plugin.normalize_spec("spec([]).")

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
    @patch("zara_coding.plugin.RepositoryInspector.inspect")
    def test_configured_plugin_returns_structured_repo_evidence(self, inspect, _which):
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
            evidence = json.loads(plugin.inspect_repo(str(repo)))
            self.assertEqual(evidence["root"], str(repo.resolve()))
            self.assertEqual(evidence["head"], "b" * 40)
            self.assertFalse(evidence["dirty"])
            inspect.assert_called_once_with(repo)

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


if __name__ == "__main__":
    unittest.main()
