from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-prolog-python-nim-shared-budgets"
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
            f"prolog_python_nim_shared_budgets_{module_name}",
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
    def __init__(self, module) -> None:
        self.module = module
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability: str) -> str:
        if capability != "expert.invoke":
            raise AssertionError(f"unexpected capability: {capability}")
        return capability

    def invoke_capability(self, _handle: str, request: dict[str, object]):
        self.requests.append(request)
        return {
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
            "data": {
                "result": {
                    "language": self.module.LANGUAGE_BOUNDARIES["language"],
                    "summary": "symbolic inspection",
                }
            },
            "evidence_refs": ["fixture:evidence"],
            "usage": {"model_calls": 0},
            "effect_receipts": [],
        }


class _NoDispatchRuntime:
    def resolve_capability(self, _capability: str):
        raise AssertionError("invalid shared budget reached capability resolution")

    def invoke_capability(self, _handle, _request):
        raise AssertionError("invalid shared budget reached capability invocation")


def _input(source: str) -> str:
    return json.dumps(
        {
            "source": source,
            "source_generation": "source:generation:1",
        }
    )


def _invoke(module, runtime, source: str, **limits: object) -> str:
    plugin = module.create_plugin()
    plugin.start(runtime)
    return plugin.invoke(
        REQUEST_ID,
        ACTIVATION_ID,
        EXPERT_OPERATION,
        EXPECTED_GENERATION,
        EXPECTED_GENERATION,
        _input(source),
        **limits,
    )


class PrologPythonNimSharedBudgetTests(unittest.TestCase):
    def test_caller_shared_budgets_are_forwarded_exactly_with_zero_model_calls(self) -> None:
        requested = {
            "timeout_ms": 17,
            "max_results": 2,
            "max_output_bytes": 4096,
        }
        for module, _error_type, source in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _Runtime(module)
                result = json.loads(_invoke(module, runtime, source, **requested))
                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(
                    runtime.requests[0]["limits"],
                    {**requested, "max_model_calls": 0},
                )
                self.assertEqual(result["usage"], {"model_calls": 0})
                self.assertEqual(result["effect_receipts"], [])

    def test_invalid_shared_budgets_fail_before_host_dispatch(self) -> None:
        invalid = (
            ("timeout_ms", 0, "invalid-timeout-ms"),
            ("timeout_ms", True, "invalid-timeout-ms"),
            ("timeout_ms", PROLOG.MAX_TIMEOUT_MS + 1, "invalid-timeout-ms"),
            ("max_results", 0, "invalid-max-results"),
            ("max_results", True, "invalid-max-results"),
            ("max_results", PROLOG.MAX_RESULTS + 1, "invalid-max-results"),
            ("max_output_bytes", 0, "invalid-max-output-bytes"),
            ("max_output_bytes", True, "invalid-max-output-bytes"),
            (
                "max_output_bytes",
                PROLOG.MAX_OUTPUT_BYTES + 1,
                "invalid-max-output-bytes",
            ),
        )
        for module, error_type, source in CASES:
            for field, value, message in invalid:
                with self.subTest(expert_id=module.EXPERT_ID, field=field, value=value):
                    with self.assertRaisesRegex(error_type, message):
                        _invoke(module, _NoDispatchRuntime(), source, **{field: value})

    def test_caller_output_budget_caps_final_projected_response(self) -> None:
        for module, error_type, source in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _Runtime(module)
                with self.assertRaisesRegex(error_type, "expert-result-too-large"):
                    _invoke(module, runtime, source, max_output_bytes=1)
                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(runtime.requests[0]["limits"]["max_output_bytes"], 1)
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
