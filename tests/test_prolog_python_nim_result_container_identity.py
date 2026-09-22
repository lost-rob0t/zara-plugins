from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from collections import UserDict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-prolog-python-nim-result-container"
ACTIVATION_ID = "act:" + ("a" * 32)
INVOCATION_ID = "inv:" + ("b" * 32)
EXPERT_OPERATION = "inspect"
EXPECTED_GENERATION = 1


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
            f"prolog_python_nim_result_container_{module_name}",
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


PROLOG = _load_plugin("zara-prolog-expert", "zara_prolog_expert")
PYTHON = _load_plugin("zara-python-expert", "zara_python_expert")
NIM = _load_plugin("zara-nim-expert", "zara_nim_expert")

CASES = (
    (PROLOG, PROLOG.PrologExpertAdapterError, "p(x)."),
    (PYTHON, PYTHON.PythonExpertAdapterError, "x = 1"),
    (NIM, NIM.NimExpertAdapterError, "let x = 1"),
)


class _ResultDict(dict):
    """Non-canonical result container with normal dict behavior."""


class _Runtime:
    def __init__(self, module, *, wrapper=None) -> None:
        self.module = module
        self.wrapper = wrapper
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability: str) -> str:
        if capability != "expert.invoke":
            raise AssertionError(f"unexpected capability: {capability}")
        return capability

    def invoke_capability(self, _handle: str, request: dict[str, object]):
        self.requests.append(request)
        result = {
            "protocol": self.module.PROTOCOL,
            "request_id": request["request_id"],
            "invocation_id": INVOCATION_ID,
            "activation_id": request["activation_id"],
            "expert_id": self.module.EXPERT_ID,
            "expert_version": self.module.PLUGIN_VERSION,
            "manifest_digest": self.module.MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "succeeded",
            "data": {"result": {"language": self.module.LANGUAGE_BOUNDARIES["language"]}},
            "evidence_refs": ["fixture:evidence"],
            "usage": {"model_calls": 0},
            "effect_receipts": [],
            "error_code": None,
            "error_message": "",
            "replayed": False,
        }
        return self.wrapper(result) if self.wrapper is not None else result


def _invoke(module, runtime: _Runtime, source: str) -> str:
    plugin = module.create_plugin()
    plugin.start(runtime)
    return plugin.invoke(
        REQUEST_ID,
        ACTIVATION_ID,
        EXPERT_OPERATION,
        EXPECTED_GENERATION,
        EXPECTED_GENERATION,
        json.dumps(
            {
                "source": source,
                "source_generation": "source:generation:1",
            }
        ),
    )


class PrologPythonNimResultContainerIdentityTests(unittest.TestCase):
    def test_builtin_dict_result_remains_canonical_zero_model(self) -> None:
        for module, _error_type, source in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _Runtime(module)
                result = json.loads(_invoke(module, runtime, source))
                self.assertEqual(result["usage"], {"model_calls": 0})
                self.assertEqual(result["effect_receipts"], [])
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_dict_subclass_result_fails_closed_before_projection(self) -> None:
        for module, error_type, source in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _Runtime(module, wrapper=_ResultDict)
                with self.assertRaisesRegex(error_type, "invalid-expert-result"):
                    _invoke(module, runtime, source)
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_generic_mapping_result_fails_closed_before_projection(self) -> None:
        for module, error_type, source in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _Runtime(module, wrapper=UserDict)
                with self.assertRaisesRegex(error_type, "invalid-expert-result"):
                    _invoke(module, runtime, source)
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
