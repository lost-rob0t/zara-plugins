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

from zara_memory.plugin import ZaraMemoryPlugin


class FakeNativeClient:
    def observe_preference(self, observation, *, scope, retention):
        return {
            "status": "stored",
            "id": "mem_pref_1",
            "durable": True,
            "observation": dict(observation),
        }

    def preference_patterns(self, query):
        return {
            "status": "ok",
            "matched_observations": 3,
            "patterns": [
                {
                    "domain": query.get("domain", "food"),
                    "item": "spicy chicken sandwich",
                    "observations": 2,
                    "positive_count": 2,
                    "negative_count": 0,
                    "preference_ratio": 1.0,
                    "positive_share": 2 / 3,
                }
            ],
        }


class PreferenceToolTests(unittest.TestCase):
    def test_constrained_preference_observation_is_automatic_but_general_memory_stays_approval_gated(self):
        tools = {tool.name: tool for tool in ZaraMemoryPlugin(native_client=FakeNativeClient()).tools()}
        self.assertIn("memory.preference.observe", tools)
        self.assertIn("memory.preference.patterns", tools)
        self.assertTrue(tools["memory.remember"].metadata["zara_requires_approval"])
        self.assertFalse(bool((tools["memory.preference.observe"].metadata or {}).get("zara_requires_approval", False)))
        self.assertFalse(bool((tools["memory.preference.patterns"].metadata or {}).get("zara_requires_approval", False)))

    def test_observation_preserves_structured_backend_evidence(self):
        plugin = ZaraMemoryPlugin(native_client=FakeNativeClient())
        result = json.loads(
            plugin.observe_preference(
                domain="food",
                item="spicy chicken sandwich",
                signal="selected",
                provider="doordash",
                merchant="Wendys",
                context={"weekday": "friday", "daypart": "late_night"},
            )
        )
        self.assertEqual(result["id"], "mem_pref_1")
        self.assertEqual(result["observation"]["provider"], "doordash")
        self.assertEqual(result["observation"]["context"]["daypart"], "late_night")

    def test_pattern_query_is_generic_not_food_specific(self):
        plugin = ZaraMemoryPlugin(native_client=FakeNativeClient())
        result = json.loads(
            plugin.preference_patterns(
                domain="shopping",
                provider="store",
                context={"daypart": "evening"},
                min_observations=2,
                limit=4,
            )
        )
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["patterns"][0]["domain"], "shopping")


if __name__ == "__main__":
    unittest.main()
