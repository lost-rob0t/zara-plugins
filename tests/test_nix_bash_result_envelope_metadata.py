from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-result-envelope"
ACTIVATION_ID = "act:" + ("d" * 32)
INVOCATION_ID = "inv:" + ("a" * 32)
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
            f"result_envelope_{module_name}",
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
        "protocol": "ZARA-EXPERT/1",
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
        "data": {"result": {}},
        "evidence_refs": ["source:fixture"],
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


class ResultEnvelopeMetadataTests(unittest.TestCase):
    def _validate(self, module, result: dict[str, object]) -> None:
        module._validate_result(
            result,
            request_id=REQUEST_ID,
            activation_id=ACTIVATION_ID,
            expert_operation=EXPERT_OPERATION,
            registry_generation=EXPECTED_GENERATION,
            runtime_generation=EXPECTED_GENERATION,
        )

    @staticmethod
    def _adapter_error(module):
        return (
            module.NixExpertAdapterError
            if module is NIX
            else module.BashExpertAdapterError
        )

    def _assert_closed_envelope(self, module) -> None:
        self._validate(module, _result(module))
        adapter_error = self._adapter_error(module)

        unknown = _result(module)
        unknown["provider_fallback"] = True
        with self.assertRaisesRegex(adapter_error, "unknown-expert-result-field"):
            self._validate(module, unknown)

        bad_error_code = _result(module)
        bad_error_code["error_code"] = object()
        with self.assertRaisesRegex(adapter_error, "invalid-expert-error-code"):
            self._validate(module, bad_error_code)

        bad_error_message = _result(module)
        bad_error_message["error_message"] = []
        with self.assertRaisesRegex(adapter_error, "invalid-expert-error-message"):
            self._validate(module, bad_error_message)

        oversized_error_message = _result(module)
        oversized_error_message["error_message"] = "x" * (module.MAX_STRING_LENGTH + 1)
        with self.assertRaisesRegex(adapter_error, "invalid-expert-error-message"):
            self._validate(module, oversized_error_message)

        bad_replayed = _result(module)
        bad_replayed["replayed"] = 1
        with self.assertRaisesRegex(adapter_error, "invalid-expert-replayed"):
            self._validate(module, bad_replayed)

        valid_metadata = _result(module)
        valid_metadata.update(
            {
                "error_code": None,
                "error_message": "",
                "replayed": False,
            }
        )
        self._validate(module, valid_metadata)

    def test_nix_closes_core_result_envelope_metadata(self) -> None:
        self._assert_closed_envelope(NIX)

    def test_bash_closes_core_result_envelope_metadata(self) -> None:
        self._assert_closed_envelope(BASH)


if __name__ == "__main__":
    unittest.main()
