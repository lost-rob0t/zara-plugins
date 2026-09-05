import json
import sys
import types
import unittest
from dataclasses import dataclass
from unittest.mock import Mock, patch
from pathlib import Path

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

from zara_coding.plugin import ZaraCodingPlugin


class RepositoryVerifyToolTests(unittest.TestCase):
    def test_verify_repository_tool_is_read_only(self):
        tools = {tool.name: tool for tool in ZaraCodingPlugin().tools()}
        tool = tools["coding.spec.verify-repository"]
        self.assertFalse(bool((tool.metadata or {}).get("zara_requires_approval", False)))

    @patch("zara_coding.plugin.verify_repository_spec")
    @patch("zara_coding.plugin.build_repository_evidence")
    def test_verify_repository_inspects_current_state_and_uses_pure_verify(self, build_evidence, verify):
        plugin = ZaraCodingPlugin()
        plugin.inspector = Mock()
        plugin.prolog_rlm = Mock()
        snapshot = {
            "root": "/srv/demo",
            "head": "a" * 40,
            "branch": "main",
            "dirty": False,
            "changed_paths": [],
        }
        evidence = {"source_class": "repository", "trust_class": "observed", "freshness": "current"}
        plugin.inspector.inspect.return_value = snapshot
        build_evidence.return_value = evidence
        verify.return_value = {"status": "ok", "outcome": "ok(verification_report{status:passed})"}

        frozen = "ok(frozen_spec{ref:spec_ref{series:zara_coding,version:1,fingerprint:'spec-sha256-deadbeef'}})"
        result = json.loads(plugin.verify_repository_spec("/srv/demo", frozen))

        self.assertEqual(result["status"], "ok")
        plugin.inspector.inspect.assert_called_once_with(Path("/srv/demo"))
        build_evidence.assert_called_once_with(snapshot)
        verify.assert_called_once_with(plugin.prolog_rlm, frozen, evidence)

    def test_verify_repository_requires_both_runtime_dependencies(self):
        plugin = ZaraCodingPlugin()
        plugin.inspector = None
        plugin.repository_reason = "allowed-roots-not-configured"
        plugin.prolog_rlm = Mock()
        with self.assertRaisesRegex(RuntimeError, "allowed-roots-not-configured"):
            plugin.verify_repository_spec("/srv/demo", "ok(frozen_spec{})")

        plugin.inspector = Mock()
        plugin.prolog_rlm = None
        with self.assertRaisesRegex(RuntimeError, "Prolog-RLM"):
            plugin.verify_repository_spec("/srv/demo", "ok(frozen_spec{})")

    def test_verify_repository_rejects_empty_inputs_before_inspection(self):
        plugin = ZaraCodingPlugin()
        plugin.inspector = Mock()
        plugin.prolog_rlm = Mock()
        with self.assertRaisesRegex(ValueError, "path"):
            plugin.verify_repository_spec("", "ok(frozen_spec{})")
        with self.assertRaisesRegex(ValueError, "frozen_spec"):
            plugin.verify_repository_spec("/srv/demo", "")
        plugin.inspector.inspect.assert_not_called()


if __name__ == "__main__":
    unittest.main()
