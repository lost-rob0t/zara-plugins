from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-four-language-input-json-type"
ACTIVATION_ID = "act:" + ("f" * 32)
EXPECTED_GENERATION = 1
INPUT_JSON = json.dumps(
    {
        "source": "const value = 1;",
        "source_generation": "source:generation:1",
    }
)


class _PluginMetadata:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ServicePlugin:
    pass


def _load_plugin(package: str, module_name: str):
    dependency_names = ("zara", "zara.plugins")
    previous = {name: sys.modules.get(name) for name in dependency_names}

    zara = types.ModuleType("zara")
    zara_plugins = types.ModuleType("zara.plugins")
    zara_plugins.PluginMetadata = _PluginMetadata
    zara_plugins.ServicePlugin = _ServicePlugin
    zara.plugins = zara_plugins

    sys.modules["zara"] = zara
    sys.modules["zara.plugins"] = zara_plugins

    try:
        path = REPO_ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
        spec = importlib.util.spec_from_file_location(
            f"four_language_request_input_json_types_{module_name}",
            path,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value


JAVASCRIPT = _load_plugin("zara-javascript-expert", "zara_javascript_expert")
TYPESCRIPT = _load_plugin("zara-typescript-expert", "zara_typescript_expert")
JAVA = _load_plugin("zara-java-expert", "zara_java_expert")
KOTLIN = _load_plugin("zara-kotlin-expert", "zara_kotlin_expert")

CASES = (
    (JAVASCRIPT, JAVASCRIPT.JavaScriptExpertAdapterError),
    (TYPESCRIPT, TYPESCRIPT.TypeScriptExpertAdapterError),
    (JAVA, JAVA.JavaExpertAdapterError),
    (KOTLIN, KOTLIN.KotlinExpertAdapterError),
)


class _ForgedJsonText(str):
    """String-shaped request input whose subtype must not cross the host boundary."""


class _NoDispatchRuntime:
    def __init__(self) -> None:
        self.resolve_calls = 0
        self.invoke_calls = 0

    def resolve_capability(self, capability: str):
        self.resolve_calls += 1
        raise AssertionError(
            f"noncanonical input_json must fail before host resolution: {capability}"
        )

    def invoke_capability(self, _handle, _request):
        self.invoke_calls += 1
        raise AssertionError("noncanonical input_json must fail before host invocation")


def _invoke(module, runtime: _NoDispatchRuntime, input_json: str) -> None:
    plugin = module.create_plugin()
    plugin.start(runtime)
    plugin.invoke(
        request_id=REQUEST_ID,
        activation_id=ACTIVATION_ID,
        expert_operation="inspect",
        expected_registry_generation=EXPECTED_GENERATION,
        expected_runtime_generation=EXPECTED_GENERATION,
        input_json=input_json,
    )


class FourLanguageRequestInputJsonTypeFenceTests(unittest.TestCase):
    def test_input_json_subclasses_fail_before_host_dispatch(self) -> None:
        for module, error_type in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _NoDispatchRuntime()
                with self.assertRaisesRegex(error_type, "input-must-be-json-text"):
                    _invoke(module, runtime, _ForgedJsonText(INPUT_JSON))
                self.assertEqual(runtime.resolve_calls, 0)
                self.assertEqual(runtime.invoke_calls, 0)


if __name__ == "__main__":
    unittest.main()
