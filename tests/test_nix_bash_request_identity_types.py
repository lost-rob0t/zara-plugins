from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req:nix-bash-request-identity"
ACTIVATION_ID = "act:" + ("e" * 32)
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
            f"request_identity_types_{module_name}",
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


class _ForgedIdentity(str):
    """String-shaped authority token with comparison behavior controlled by caller."""

    def __eq__(self, other: object) -> bool:
        return True

    __hash__ = str.__hash__


class _NoDispatchRuntime:
    def resolve_capability(self, capability: str):
        raise AssertionError(
            f"forged identity must fail before host resolution: {capability}"
        )

    def invoke_capability(self, _handle, _request):
        raise AssertionError("forged identity must fail before host invocation")


class RequestIdentityTypeFenceTests(unittest.TestCase):
    @staticmethod
    def _adapter_error(module):
        return (
            module.NixExpertAdapterError
            if module is NIX
            else module.BashExpertAdapterError
        )

    def _invoke(
        self,
        module,
        *,
        request_id: str = REQUEST_ID,
        activation_id: str = ACTIVATION_ID,
    ) -> None:
        plugin = module.create_plugin()
        plugin.start(_NoDispatchRuntime())
        plugin.invoke(
            request_id=request_id,
            activation_id=activation_id,
            expert_operation="inspect",
            expected_registry_generation=EXPECTED_GENERATION,
            expected_runtime_generation=EXPECTED_GENERATION,
            input_json=json.dumps(
                {"source": "x = 1", "source_generation": "fixture:1"}
            ),
        )

    def _assert_module_rejects_forged_identity(self, module) -> None:
        adapter_error = self._adapter_error(module)

        with self.subTest(module=module.__name__, field="request_id"):
            with self.assertRaisesRegex(adapter_error, "invalid-request-id"):
                self._invoke(module, request_id=_ForgedIdentity(REQUEST_ID))

        with self.subTest(module=module.__name__, field="activation_id"):
            with self.assertRaisesRegex(adapter_error, "invalid-activation-id"):
                self._invoke(module, activation_id=_ForgedIdentity(ACTIVATION_ID))

    def test_nix_rejects_noncanonical_request_identity_strings(self) -> None:
        self._assert_module_rejects_forged_identity(NIX)

    def test_bash_rejects_noncanonical_request_identity_strings(self) -> None:
        self._assert_module_rejects_forged_identity(BASH)


if __name__ == "__main__":
    unittest.main()
