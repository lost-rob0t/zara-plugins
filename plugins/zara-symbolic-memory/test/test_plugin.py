import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

plugins = types.ModuleType("zara.plugins")


class PluginMetadata:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ServicePlugin:
    pass


class StartupUnavailable:
    def __init__(self, reason):
        self.reason = reason


plugins.PluginMetadata = PluginMetadata
plugins.ServicePlugin = ServicePlugin
plugins.StartupUnavailable = StartupUnavailable
zara = types.ModuleType("zara")
zara.plugins = plugins
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", plugins)

from zara_symbolic_memory import plugin as plugin_module


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration
        self.registrations = []

    def register_symbol(self, symbol, kind, value, **kwargs):
        self.registrations.append((symbol, kind, value, kwargs))
        return len(self.registrations)


class Principal:
    def __init__(self, principal_id):
        self.principal_id = principal_id


class FakeQueryEngine:
    def __init__(self, results):
        self.results = results

    def query(self, query, *, scope, limit):
        return {"status": "ok", "count": len(self.results), "results": self.results[:limit]}


class PluginTest(unittest.TestCase):
    def start_plugin(self, directory):
        instance = plugin_module.create_plugin()
        runtime = Runtime(
            {
                "data_dir": directory,
                "embedding_backend": "disabled",
                "require_prolog": False,
            }
        )
        result = instance.start(runtime)
        self.assertIsNone(result)
        return instance, runtime

    def test_metadata_and_registers_canonical_memory_provider_symbol(self):
        with tempfile.TemporaryDirectory() as directory:
            instance, runtime = self.start_plugin(directory)
            self.assertEqual(instance.metadata.name, "zara-symbolic-memory")
            self.assertEqual(instance.metadata.version, "0.1.0")
            self.assertEqual(len(runtime.registrations), 1)
            symbol, kind, value, metadata = runtime.registrations[0]
            self.assertEqual(symbol, "memory.provider")
            self.assertEqual(kind, "memory-provider")
            self.assertIs(value, instance)
            self.assertIn("Prolog", metadata["docs"])
            status = instance.status()
            self.assertIn('"embedding_backend": null', status)
            instance.stop()

    def test_require_prolog_reports_unavailable_without_registering_provider(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = plugin_module.create_plugin()
            runtime = Runtime({"data_dir": directory, "embedding_backend": "disabled", "require_prolog": True})
            result = instance.start(runtime)
            if instance.engine.ready():
                self.assertIsNone(result)
                self.assertEqual(len(runtime.registrations), 1)
            else:
                self.assertIsInstance(result, StartupUnavailable)
                self.assertEqual(result.reason, "swipl-unavailable")
                self.assertEqual(runtime.registrations, [])
            instance.stop()

    def test_memory_manager_compatibility_is_principal_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            instance, _runtime = self.start_plugin(directory)
            instance.bind_principal(Principal("alice"))
            session = instance.start_session("session-a")
            instance.add_message(session, "user", "I like red")
            instance.add_message(session, "assistant", "Noted")
            memory_id = instance.remember_fact("I prefer red", tags=["preference"], source="agent")
            self.assertTrue(memory_id)
            active = instance.store.active_records()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0].scope, "principal:alice")
            payload = json.loads(active[0].object_json)
            self.assertEqual(payload["text"], "I prefer red")
            self.assertEqual(payload["tags"], ["preference"])
            self.assertEqual(instance.current_session_id, "session-a")
            instance.stop()

    def test_retrieve_adapts_prolog_ranked_results_to_memory_manager_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            instance, _runtime = self.start_plugin(directory)
            instance.bind_principal(Principal("alice"))
            instance.engine = FakeQueryEngine(
                [
                    {
                        "type": "memory",
                        "memory_id": "m1",
                        "text": "I prefer red",
                        "object_json": json.dumps({"kind": "fact", "tags": ["preference"], "session_id": ""}),
                        "source": "user",
                        "created_at": "2026-09-20T00:00:00+00:00",
                        "score": 0.9,
                    },
                    {
                        "type": "kb",
                        "clause_id": "k1",
                        "source": "/kb/facts.pl",
                        "text": "likes(user, red).",
                        "score": 0.7,
                    },
                ]
            )
            results = instance.retrieve("red", k=5)
            self.assertEqual(results[0]["id"], "m1")
            self.assertEqual(results[0]["metadata"]["kind"], "fact")
            self.assertEqual(results[1]["metadata"]["kind"], "prolog-kb")
            self.assertEqual(results[1]["text"], "likes(user, red).")
            instance.stop()

    def test_forget_all_tombstones_only_bound_principal_memories(self):
        with tempfile.TemporaryDirectory() as directory:
            instance, _runtime = self.start_plugin(directory)
            instance.bind_principal(Principal("alice"))
            instance.remember_fact("Alice fact")
            instance.bind_principal(Principal("bob"))
            instance.remember_fact("Bob fact")
            self.assertEqual(instance.forget(all_memories=True), 1)
            active = instance.store.active_records()
            self.assertEqual(len(active), 1)
            self.assertEqual(active[0].scope, "principal:alice")
            instance.stop()


if __name__ == "__main__":
    unittest.main()
