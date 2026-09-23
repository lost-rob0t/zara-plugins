from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-result-identity-type-fence"
ACTIVATION_ID = "act:" + ("c" * 32)
INVOCATION_ID = "inv:" + ("d" * 32)
EXPERT_OPERATION = "inspect"
EXPECTED_GENERATION = 1


class _PluginMetadata:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class _ServicePlugin:
    pass


class _StructuredTool:
    pass


class _MasqueradingString(str):
    """Visible forged value whose comparisons claim canonical identity."""

    def __new__(cls):
        return super().__new__(cls, "forged-provider-shaped-identity")

    def __eq__(self, _other):
        return True

    def __ne__(self, _other):
        return False


class _Runtime:
    def __init__(self, result: dict[str, object]):
        self.result = result
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability: str):
        if capability != "expert.invoke":
            raise AssertionError(capability)
        return object()

    def invoke_capability(self, _handle, request: dict[str, object]):
        self.requests.append(request)
        return self.result


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
            f"result_identity_type_fence_{module_name}",
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


class ResultIdentityTypeFenceTests(unittest.TestCase):
    def _assert_identity_type_fence(self, module) -> None:
        adapter_error = (
            module.NixExpertAdapterError
            if module is NIX
            else module.BashExpertAdapterError
        )
        identity_fields = (
            "protocol",
            "request_id",
            "activation_id",
            "expert_id",
            "expert_version",
            "manifest_digest",
            "expert_operation",
        )

        for field in identity_fields:
            with self.subTest(expert_id=module.EXPERT_ID, field=field):
                result = _result(module)
                result[field] = _MasqueradingString()
                runtime = _Runtime(result)
                plugin = module.create_plugin()
                plugin.start(runtime)

                with self.assertRaisesRegex(
                    adapter_error,
                    "expert-result-identity-mismatch",
                ):
                    plugin.invoke(
                        request_id=REQUEST_ID,
                        activation_id=ACTIVATION_ID,
                        expert_operation=EXPERT_OPERATION,
                        expected_registry_generation=EXPECTED_GENERATION,
                        expected_runtime_generation=EXPECTED_GENERATION,
                        input_json=(
                            '{"source":"let x = 1; in x",'
                            '"source_generation":"fixture:identity:1"}'
                        ),
                    )

                self.assertEqual(len(runtime.requests), 1)
                request = runtime.requests[0]
                self.assertEqual(request["operation"], "expert.invoke")
                self.assertEqual(request["limits"]["max_model_calls"], 0)
                self.assertEqual(result["usage"], {"model_calls": 0})
                self.assertEqual(result["effect_receipts"], [])

    def test_nix_rejects_comparison_masquerading_identity_values(self) -> None:
        self._assert_identity_type_fence(NIX)

    def test_bash_rejects_comparison_masquerading_identity_values(self) -> None:
        self._assert_identity_type_fence(BASH)


if __name__ == "__main__":
    unittest.main()
