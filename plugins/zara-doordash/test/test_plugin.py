import json
import sys
import types
import unittest
from dataclasses import dataclass
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

from zara_doordash.plugin import ZaraDoorDashPlugin


@dataclass(frozen=True)
class Handle:
    capability: str


class Runtime:
    def __init__(self):
        self.configuration = {
            "commerce_provider": "doordash",
            "commerce_confirmation": "always",
            "learning_enabled": True,
            "preference_min_observations": 2,
            "preference_limit": 5,
            "preference_min_confidence": 0.6,
            "policy_source": "prolog",
        }
        self.calls = []
        self.resolve_calls = []

    def resolve_capability(self, capability):
        self.resolve_calls.append(capability)
        if capability in {
            "browser.tab.open",
            "memory.preference.observe",
            "memory.preference.patterns",
        }:
            return Handle(capability)
        raise LookupError(capability)

    def invoke_capability(self, handle, request):
        self.calls.append((handle.capability, dict(request)))
        if handle.capability == "browser.tab.open":
            return json.dumps({"tab_id": "tab-1", "url": request["url"]})
        if handle.capability == "memory.preference.observe":
            return json.dumps({"status": "stored", "id": "mem_pref_1"})
        if handle.capability == "memory.preference.patterns":
            return json.dumps(
                {
                    "status": "ok",
                    "matched_observations": 3,
                    "patterns": [
                        {"item": "tacos", "positive_count": 3, "confidence": 0.9},
                        {"item": "pizza", "positive_count": 2, "confidence": 0.4},
                    ],
                }
            )
        raise AssertionError(handle.capability)


class DoorDashPluginTests(unittest.TestCase):
    def test_checkout_is_canonical_approval_gated(self):
        plugin = ZaraDoorDashPlugin()
        tools = {tool.name: tool for tool in plugin.tools()}
        self.assertEqual(
            set(tools),
            {
                "doordash.status",
                "doordash.prepare",
                "doordash.checkout",
                "doordash.preferences",
            },
        )
        self.assertTrue(tools["doordash.checkout"].metadata["zara_requires_approval"])
        self.assertFalse(bool((tools["doordash.prepare"].metadata or {}).get("zara_requires_approval", False)))

    def test_start_consumes_plugin_scoped_policy_without_resolving_dependencies(self):
        runtime = Runtime()
        plugin = ZaraDoorDashPlugin()

        plugin.start(runtime)

        self.assertEqual(runtime.resolve_calls, [])
        self.assertEqual(plugin.preference_min_observations, 2)
        self.assertEqual(plugin.preference_limit, 5)
        self.assertEqual(plugin.preference_min_confidence, 0.6)
        self.assertEqual(plugin.policy_source, "prolog")

    def test_approved_checkout_handoff_opens_browser_and_records_selection(self):
        runtime = Runtime()
        plugin = ZaraDoorDashPlugin()
        plugin.start(runtime)
        result = json.loads(
            plugin.checkout(
                item="tacos",
                merchant="Taco Shop",
                context={"weekday": "friday"},
            )
        )
        self.assertEqual(result["status"], "handoff_opened")
        self.assertFalse(result["purchase_completed"])
        self.assertEqual(result["learning"]["status"], "stored")
        capabilities = [name for name, _ in runtime.calls]
        self.assertEqual(capabilities, ["browser.tab.open", "memory.preference.observe"])
        observation = runtime.calls[1][1]
        self.assertEqual(observation["domain"], "food")
        self.assertEqual(observation["item"], "tacos")
        self.assertEqual(observation["provider"], "doordash")

    def test_preferences_use_generic_memory_pattern_capability(self):
        runtime = Runtime()
        plugin = ZaraDoorDashPlugin()
        plugin.start(runtime)
        result = json.loads(
            plugin.preferences(context={"daypart": "late_night"})
        )
        self.assertEqual([item["item"] for item in result["patterns"]], ["tacos"])
        capability, request = runtime.calls[-1]
        self.assertEqual(capability, "memory.preference.patterns")
        self.assertEqual(request["domain"], "food")
        self.assertEqual(request["provider"], "doordash")
        self.assertEqual(request["min_observations"], 2)

    def test_handoff_degrades_honestly_when_composed_browser_is_missing(self):
        class NoCapabilities(Runtime):
            def resolve_capability(self, capability):
                raise LookupError(capability)

        plugin = ZaraDoorDashPlugin()
        plugin.start(NoCapabilities())
        result = json.loads(plugin.checkout(item="pizza"))
        self.assertEqual(result["status"], "handoff_ready")
        self.assertFalse(result["purchase_completed"])
        self.assertEqual(result["browser"]["status"], "unavailable")
        self.assertEqual(result["learning"]["status"], "not_observed")
        self.assertEqual(
            [name for name, _ in plugin.runtime.calls],
            [],
        )


if __name__ == "__main__":
    unittest.main()
