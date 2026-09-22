from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from collections.abc import Iterator, Mapping
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-four-language-result-mapping"
ACTIVATION_ID = "act:" + ("c" * 32)
INVOCATION_ID = "inv:" + ("d" * 32)
EXPERT_OPERATION = "inspect"
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
            f"four_language_result_mapping_{module_name}",
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


def _canonical_result(module, request: dict[str, object]) -> dict[str, object]:
    return {
        "protocol": module.PROTOCOL,
        "request_id": request["request_id"],
        "invocation_id": INVOCATION_ID,
        "activation_id": request["activation_id"],
        "expert_id": module.EXPERT_ID,
        "expert_version": module.PLUGIN_VERSION,
        "manifest_digest": module.MANIFEST_DIGEST,
        "expert_operation": request["expert_operation"],
        "resolved_registry_generation": request["expected_registry_generation"],
        "resolved_runtime_generation": request["expected_runtime_generation"],
        "verdict": "succeeded",
        "data": {"result": {}},
        "evidence_refs": [],
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


class _DeceptiveResult(Mapping[str, object]):
    """Expose a valid envelope once, then inject provider-shaped metadata."""

    def __init__(self, values: dict[str, object]) -> None:
        self._values = values
        self._iterations = 0

    def __getitem__(self, key: str) -> object:
        if key == "provider_fallback":
            return True
        return self._values[key]

    def __iter__(self) -> Iterator[str]:
        self._iterations += 1
        yield from self._values
        if self._iterations > 1:
            yield "provider_fallback"

    def __len__(self) -> int:
        return len(self._values) + 1


class _Runtime:
    def __init__(self, module) -> None:
        self.module = module
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability: str) -> str:
        if capability != "expert.invoke":
            raise AssertionError(f"unexpected capability: {capability}")
        return capability

    def invoke_capability(self, _handle: str, request: dict[str, object]) -> Mapping[str, object]:
        self.requests.append(request)
        return _DeceptiveResult(_canonical_result(self.module, request))


def _invoke(module, runtime: _Runtime) -> str:
    plugin = module.create_plugin()
    plugin.start(runtime)
    return plugin.invoke(
        REQUEST_ID,
        ACTIVATION_ID,
        EXPERT_OPERATION,
        EXPECTED_GENERATION,
        EXPECTED_GENERATION,
        INPUT_JSON,
    )


class FourLanguageResultMappingFenceTests(unittest.TestCase):
    def test_deceptive_result_mapping_fails_closed_before_projection(self) -> None:
        for module, error_type in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _Runtime(module)
                with self.assertRaisesRegex(error_type, "invalid-expert-result"):
                    _invoke(module, runtime)
                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
