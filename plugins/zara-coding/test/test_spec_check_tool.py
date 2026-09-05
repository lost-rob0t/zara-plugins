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


class RepositorySpecCheckToolTests(unittest.TestCase):
    def test_check_repository_tool_is_read_only(self):
        tools = {tool.name: tool for tool in ZaraCodingPlugin().tools()}
        tool = tools["coding.spec.check-repository"]
        self.assertFalse(bool((tool.metadata or {}).get("zara_requires_approval", False)))

    @patch("zara_coding.plugin.compile_spec")
    def test_check_repository_freezes_then_verifies_same_frozen_spec(self, compile_source):
        plugin = ZaraCodingPlugin()
        plugin.prolog_rlm = Mock()
        frozen = "ok(frozen_spec{ref:spec_ref{series:zara_coding,version:1,fingerprint:'spec-sha256-deadbeef'}})"
        compile_source.return_value = {"status": "ok", "outcome": frozen}
        plugin.verify_repository_spec = Mock(
            return_value=json.dumps(
                {"status": "ok", "outcome": "ok(verification_report{status:passed})"},
                sort_keys=True,
            )
        )
        source = "spec([subject(repository(demo)),require(clean,assertion(repository_clean,_{root:'/srv/demo',clean:true}))])."

        result = json.loads(plugin.check_repository_spec("/srv/demo", source))

        self.assertEqual(result["compile"]["status"], "ok")
        self.assertIn("verification_report", result["verification"]["outcome"])
        compile_source.assert_called_once_with(plugin.prolog_rlm, source)
        plugin.verify_repository_spec.assert_called_once_with("/srv/demo", frozen)

    @patch("zara_coding.plugin.compile_spec")
    def test_check_repository_preserves_compile_rejection_without_inspection(self, compile_source):
        plugin = ZaraCodingPlugin()
        plugin.prolog_rlm = Mock()
        compile_source.return_value = {
            "status": "rejected",
            "outcome": "error(spec_lang_error{reason:invalid_requirement})",
        }
        plugin.verify_repository_spec = Mock(side_effect=AssertionError("verification must not run"))

        result = json.loads(plugin.check_repository_spec("/srv/demo", "spec([subject(x)])."))

        self.assertEqual(result["compile"]["status"], "rejected")
        self.assertIsNone(result["verification"])
        plugin.verify_repository_spec.assert_not_called()

    def test_check_repository_rejects_empty_inputs_before_prolog(self):
        plugin = ZaraCodingPlugin()
        plugin.prolog_rlm = Mock()
        with self.assertRaisesRegex(ValueError, "path"):
            plugin.check_repository_spec("", "spec([subject(x)]).")
        with self.assertRaisesRegex(ValueError, "source"):
            plugin.check_repository_spec("/srv/demo", "")


if __name__ == "__main__":
    unittest.main()
