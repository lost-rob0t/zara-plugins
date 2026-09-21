from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-core-evidence-bounds"
ACTIVATION_ID = "act:" + ("d" * 32)
INVOCATION_ID = "inv:" + ("c" * 32)
EXPERT_OPERATION = "parse"
EXPECTED_GENERATION = 1
CORE_MAX_EVIDENCE_REFS = 32
CORE_MAX_EVIDENCE_REF_LENGTH = 128


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
            f"core_evidence_bounds_{module_name}",
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


def _result(module, evidence_refs: list[str]) -> dict[str, object]:
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
        "evidence_refs": evidence_refs,
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


def _validate(module, evidence_refs: list[str]) -> None:
    module._validate_result(
        _result(module, evidence_refs),
        request_id=REQUEST_ID,
        activation_id=ACTIVATION_ID,
        expert_operation=EXPERT_OPERATION,
        registry_generation=EXPECTED_GENERATION,
        runtime_generation=EXPECTED_GENERATION,
    )


class CoreEvidenceBoundsTests(unittest.TestCase):
    def _assert_contract(self, module) -> None:
        self.assertEqual(module.MAX_EVIDENCE_REFS, CORE_MAX_EVIDENCE_REFS)
        self.assertEqual(
            module.MAX_EVIDENCE_REF_LENGTH,
            CORE_MAX_EVIDENCE_REF_LENGTH,
        )

        exact_ref = "e:" + ("a" * (CORE_MAX_EVIDENCE_REF_LENGTH - 2))
        _validate(module, [exact_ref] * CORE_MAX_EVIDENCE_REFS)

        adapter_error = (
            module.NixExpertAdapterError
            if module is NIX
            else module.BashExpertAdapterError
        )
        with self.assertRaisesRegex(adapter_error, "invalid-expert-evidence"):
            _validate(
                module,
                ["source:fixture"] * (CORE_MAX_EVIDENCE_REFS + 1),
            )
        with self.assertRaisesRegex(adapter_error, "invalid-expert-evidence"):
            _validate(module, [exact_ref + "x"])

    def test_nix_evidence_matches_core_bounds(self) -> None:
        self._assert_contract(NIX)

    def test_bash_evidence_matches_core_bounds(self) -> None:
        self._assert_contract(BASH)


if __name__ == "__main__":
    unittest.main()
