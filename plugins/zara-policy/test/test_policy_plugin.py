from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

ENTRY = Path(__file__).resolve().parents[1] / "zara-plugin" / "zara_policy.py"


def load_plugin():
    api = ModuleType("zara.plugins.api")
    @dataclass
    class Metadata:
        name: str
        version: str
        description: str
    api.PluginMetadata = Metadata
    api.ServicePlugin = type("ServicePlugin", (), {})
    spec = importlib.util.spec_from_file_location("policy_plugin_under_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"zara.plugins.api": api}):
        spec.loader.exec_module(module)
    return module


class Runtime:
    def __init__(self):
        self.registrations = []
    def register_agent_loop_advice(self, *args):
        self.registrations.append(args)
        return 1


class PolicyPluginTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.env = patch.dict(os.environ, {"XDG_CONFIG_HOME": self.directory.name})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.root = Path(self.directory.name) / "zarathushtra/plugins/zara-policy"
        self.root.mkdir(parents=True)
        self.rules = self.root / "policy.pl"
        self.rules.write_text("% operator rules\n")
        self.module = load_plugin()
        self.runtime = Runtime()
        self.plugin = self.module.create_plugin()

    def test_metadata_and_owned_registration(self):
        self.plugin.start(self.runtime)
        self.assertEqual(self.plugin.metadata.name, "zara-policy")
        self.assertEqual(self.plugin.metadata.version, "0.1.0")
        kind, priority, callback = self.runtime.registrations[0]
        self.assertEqual((kind, priority), ("around", 100))
        self.assertTrue(callable(callback))

    def test_missing_rules_fails_before_hook_registration(self):
        self.rules.unlink()
        with self.assertRaisesRegex(RuntimeError, "policy.pl"):
            self.plugin.start(self.runtime)
        self.assertFalse(self.runtime.registrations)

    def test_invalid_private_settings(self):
        for contents in ('max_revisions = true', 'max_revisions = 4', 'max_revisions = -1', 'other = 1'):
            with self.subTest(contents=contents):
                (self.root / "config.toml").write_text(contents)
                with self.assertRaises((ValueError, RuntimeError)):
                    self.module.create_plugin().start(self.runtime)
        self.assertFalse(self.runtime.registrations)

    def test_double_start_rejected(self):
        self.plugin.start(self.runtime)
        with self.assertRaises(RuntimeError):
            self.plugin.start(self.runtime)
        self.assertEqual(len(self.runtime.registrations), 1)

    async def test_native_mode_does_not_require_policy_engine_or_model(self):
        self.plugin.start(self.runtime)
        calls = []
        async def continuation(*args, **kwargs):
            calls.append((args, kwargs))
            return {"response": "true."}
        result = await self.plugin._around(continuation, None, None, {"backend": "prolog"})
        self.assertEqual(result["response"], "true.")
        self.assertEqual(len(calls), 1)

    async def test_stopped_callback_fails_closed(self):
        self.plugin.start(self.runtime)
        self.plugin.stop()
        async def continuation(*args, **kwargs):
            self.fail("closed hook must not run")
        with self.assertRaises(RuntimeError):
            await self.plugin._around(continuation, object(), None, {})

    async def test_wraps_only_model_consults_once_and_uses_host_context(self):
        self.plugin.start(self.runtime)
        calls, consulted, policies = [], [], []
        engine = SimpleNamespace(consult=consulted.append, query_once=lambda _: {})
        registry = SimpleNamespace(prolog_engine=engine)
        model = object()
        adapter = ModuleType("zara.agent.output_policy")
        class Policy:
            def __init__(self, engine_arg, context):
                policies.append((engine_arg, context))
            def evaluate(self, text):
                return ()
        class Model:
            def __init__(self, model_arg, evaluator, **kwargs):
                self.model = model_arg
                self.settings = kwargs
        adapter.PrologPolicy, adapter.AdvisedModel = Policy, Model
        async def continuation(model_arg, registry_arg, state, **kwargs):
            calls.append((model_arg, registry_arg, state, kwargs))
            return {"response": "accepted"}
        with patch.dict(sys.modules, {"zara.agent.output_policy": adapter}):
            for turn in ("one", "two"):
                result = await self.plugin._around(
                    continuation, model, registry, {"turn_id": turn, "conversation_id": "c"},
                    principal_id="actual-host-principal")
                self.assertEqual(result["response"], "accepted")
        self.assertEqual(consulted, [self.rules])
        self.assertEqual(len(calls), 2)
        self.assertIs(calls[0][0].model, model)
        self.assertIs(calls[0][1], registry)
        self.assertEqual(policies[0][1]["principal_id"], "actual-host-principal")
        self.assertEqual(policies[1][1]["turn_id"], "two")
        self.assertEqual(calls[0][0].settings, {"max_revisions": 2})

    async def test_missing_engine_never_runs_continuation(self):
        self.plugin.start(self.runtime)
        adapter = ModuleType("zara.agent.output_policy")
        adapter.AdvisedModel = object
        adapter.PrologPolicy = object
        async def continuation(*args, **kwargs):
            self.fail("missing engine must fail closed")
        with patch.dict(sys.modules, {"zara.agent.output_policy": adapter}):
            with self.assertRaisesRegex(RuntimeError, "canonical Prolog"):
                await self.plugin._around(continuation, object(), SimpleNamespace(), {})

    async def test_failed_consult_is_sanitized_and_not_marked_loaded(self):
        self.plugin.start(self.runtime)
        adapter = ModuleType("zara.agent.output_policy")
        adapter.AdvisedModel = object
        adapter.PrologPolicy = object
        def fail(path):
            raise ValueError("private-rule-body")
        engine = SimpleNamespace(consult=fail, query_once=lambda _: {})
        async def continuation(*args, **kwargs):
            self.fail("failed consult must fail closed")
        with patch.dict(sys.modules, {"zara.agent.output_policy": adapter}):
            with self.assertRaises(RuntimeError) as error:
                await self.plugin._around(continuation, object(), SimpleNamespace(prolog_engine=engine), {})
        self.assertNotIn("private-rule-body", str(error.exception))
        self.assertIsNone(self.plugin._loaded_engine)


if __name__ == "__main__":
    unittest.main()
