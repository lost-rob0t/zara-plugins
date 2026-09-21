from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-prolog-python-nim-result-metadata"
ACTIVATION_ID = "act:" + ("a" * 32)
INVOCATION_ID = "inv:" + ("b" * 32)
EXPERT_OPERATION = "inspect"
EXPECTED_GENERATION = 1
MAX_ERROR_MESSAGE_LENGTH = 4096


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
            f"prolog_python_nim_result_metadata_{module_name}",
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


class _Runtime:
    def __init__(self, module, *, extra_result: dict[object, object] | None = None) -> None:
        self.module = module
        self.extra_result = extra_result or {}
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability: str) -> str:
        if capability != "expert.invoke":
            raise AssertionError(f"unexpected capability: {capability}")
        return capability

    def invoke_capability(self, _handle: str, request: dict[str, object]):
        self.requests.append(request)
        result: dict[object, object] = {
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
        }
        result.update(self.extra_result)
        return result


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


class PrologPythonNimResultMetadataContractTests(unittest.TestCase):
    def test_canonical_optional_metadata_remains_zero_model(self) -> None:
        for module, _error_type, source in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _Runtime(
                    module,
                    extra_result={
                        "error_code": None,
                        "error_message": "",
                        "replayed": False,
                    },
                )
                result = json.loads(_invoke(module, runtime, source))
                self.assertIsNone(result["error_code"])
                self.assertEqual(result["error_message"], "")
                self.assertIs(result["replayed"], False)
                self.assertEqual(result["usage"], {"model_calls": 0})
                self.assertEqual(result["effect_receipts"], [])
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_error_code_is_canonical_or_null(self) -> None:
        for module, error_type, source in CASES:
            for error_code in (object(), "provider_error", "cancelled ", 7):
                with self.subTest(expert_id=module.EXPERT_ID, error_code=repr(error_code)):
                    runtime = _Runtime(module, extra_result={"error_code": error_code})
                    with self.assertRaisesRegex(error_type, "invalid-expert-error-code"):
                        _invoke(module, runtime, source)
                    self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_error_message_is_exact_string_and_bounded(self) -> None:
        class StringSubclass(str):
            pass

        for module, error_type, source in CASES:
            for error_message in (
                [],
                7,
                StringSubclass("masquerade"),
                "x" * (MAX_ERROR_MESSAGE_LENGTH + 1),
            ):
                with self.subTest(
                    expert_id=module.EXPERT_ID,
                    message_type=type(error_message).__name__,
                ):
                    runtime = _Runtime(module, extra_result={"error_message": error_message})
                    with self.assertRaisesRegex(error_type, "invalid-expert-error-message"):
                        _invoke(module, runtime, source)

    def test_replayed_requires_exact_bool(self) -> None:
        class BoolLike(int):
            pass

        for module, error_type, source in CASES:
            for replayed in (0, 1, "false", None, BoolLike(0)):
                with self.subTest(expert_id=module.EXPERT_ID, replayed=repr(replayed)):
                    runtime = _Runtime(module, extra_result={"replayed": replayed})
                    with self.assertRaisesRegex(error_type, "invalid-expert-replayed"):
                        _invoke(module, runtime, source)
                    self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
