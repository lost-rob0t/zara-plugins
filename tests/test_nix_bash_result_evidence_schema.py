from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-result-evidence-schema"
ACTIVATION_ID = "act:" + ("d" * 32)
INVOCATION_ID = "inv:" + ("c" * 32)
EXPERT_OPERATION = "inspect"
EXPECTED_GENERATION = 1


class _PluginMetadata:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ServicePlugin:
    pass


class _StructuredTool:
    pass


def _load_plugin(package: str, module_name: str):
    dependency_names = (
        "langchain_core",
        "langchain_core.tools",
        "zara",
        "zara.plugins",
    )
    previous = {name: sys.modules.get(name) for name in dependency_names}

    langchain_core = types.ModuleType("langchain_core")
    langchain_tools = types.ModuleType("langchain_core.tools")
    langchain_tools.StructuredTool = _StructuredTool
    langchain_core.tools = langchain_tools

    zara = types.ModuleType("zara")
    zara_plugins = types.ModuleType("zara.plugins")
    zara_plugins.PluginMetadata = _PluginMetadata
    zara_plugins.ServicePlugin = _ServicePlugin
    zara.plugins = zara_plugins

    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.tools"] = langchain_tools
    sys.modules["zara"] = zara
    sys.modules["zara.plugins"] = zara_plugins

    try:
        path = REPO_ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
        spec = importlib.util.spec_from_file_location(
            f"result_evidence_schema_{module_name}",
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


NIX = _load_plugin("zara-nix-expert", "zara_nix_expert")
BASH = _load_plugin("zara-bash-expert", "zara_bash_expert")


def _result(module) -> dict[str, object]:
    return {
        "protocol": module.PROTOCOL,
        "request_id": REQUEST_ID,
        "invocation_id": INVOCATION_ID,
        "activation_id": ACTIVATION_ID,
        "expert_id": module.EXPERT_ID,
        "expert_version": module.PLUGIN_VERSION,
        "manifest_digest": module.MANIFEST_DIGEST,
        "expert_operation": EXPERT_OPERATION,
        "resolved_registry_generation": EXPECTED_GENERATION,
        "resolved_runtime_generation": EXPECTED_GENERATION,
        "verdict": "succeeded",
        "data": {"verdict": "clean"},
        "evidence_refs": ["source:fixture"],
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


class ResultEvidenceSchemaTests(unittest.TestCase):
    def _assert_rejected(self, module, mutation: dict[str, object], error: str) -> None:
        result = _result(module)
        result.update(mutation)
        adapter_error = (
            module.NixExpertAdapterError
            if module is NIX
            else module.BashExpertAdapterError
        )
        with self.assertRaisesRegex(adapter_error, error):
            module._validate_result(
                result,
                request_id=REQUEST_ID,
                activation_id=ACTIVATION_ID,
                expert_operation=EXPERT_OPERATION,
                registry_generation=EXPECTED_GENERATION,
                runtime_generation=EXPECTED_GENERATION,
            )

    def _assert_result_schema(self, module) -> None:
        for data in (None, [], "clean", 1):
            with self.subTest(expert_id=module.EXPERT_ID, data=data):
                self._assert_rejected(module, {"data": data}, "invalid-expert-data")

        invalid_evidence = (
            None,
            "source:fixture",
            [1],
            [""],
            ["source:fixture", None],
        )
        for evidence_refs in invalid_evidence:
            with self.subTest(
                expert_id=module.EXPERT_ID,
                evidence_refs=evidence_refs,
            ):
                self._assert_rejected(
                    module,
                    {"evidence_refs": evidence_refs},
                    "invalid-expert-evidence",
                )

        invalid_json_data = (
            ("set", {"value": {"not-json"}}),
            ("bytes", {"value": b"not-json"}),
            ("nan", {"value": float("nan")}),
            ("positive-infinity", {"value": float("inf")}),
            ("negative-infinity", {"value": float("-inf")}),
            ("non-string-key", {1: "not-json-object"}),
        )
        for case, data in invalid_json_data:
            with self.subTest(expert_id=module.EXPERT_ID, case=case):
                self._assert_rejected(
                    module,
                    {"data": data},
                    "invalid-expert-data-json",
                )

        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        with self.subTest(expert_id=module.EXPERT_ID, case="cycle"):
            self._assert_rejected(
                module,
                {"data": cyclic},
                "invalid-expert-data-json",
            )

    def test_nix_result_data_and_evidence_are_typed(self) -> None:
        self._assert_result_schema(NIX)

    def test_bash_result_data_and_evidence_are_typed(self) -> None:
        self._assert_result_schema(BASH)


if __name__ == "__main__":
    unittest.main()
