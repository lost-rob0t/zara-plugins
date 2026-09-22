from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOST_LIB = ROOT / "plugins" / "zara-expert" / "lib"
if str(HOST_LIB) not in sys.path:
    sys.path.insert(0, str(HOST_LIB))

ACTIVATION_ID = "act:" + "a" * 32
INVOCATION_ID = "inv:" + "b" * 32
CASES = {
    "nix": (
        "zara-nix-expert",
        "zara_nix_expert",
        "Nix",
        {"source": "{ x = 1; }"},
    ),
    "bash": (
        "zara-bash-expert",
        "zara_bash_expert",
        "Bash",
        {"source": "printf '%s\\n' ok"},
    ),
}


def _install_dependency_stubs() -> None:
    langchain_core = types.ModuleType("langchain_core")
    langchain_tools = types.ModuleType("langchain_core.tools")

    class StructuredTool:
        pass

    langchain_tools.StructuredTool = StructuredTool
    langchain_core.tools = langchain_tools
    sys.modules["langchain_core"] = langchain_core
    sys.modules["langchain_core.tools"] = langchain_tools

    plugins = types.ModuleType("zara.plugins")

    class PluginMetadata:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class ServicePlugin:
        pass

    plugins.PluginMetadata = PluginMetadata
    plugins.ServicePlugin = ServicePlugin
    zara = types.ModuleType("zara")
    zara.plugins = plugins
    sys.modules["zara"] = zara
    sys.modules["zara.plugins"] = plugins


def _load_plugin(package: str, module_name: str, suffix: str):
    _install_dependency_stubs()
    path = ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        f"test_nix_bash_terminal_fence_{module_name}_{suffix}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TerminalFenceRuntime:
    def __init__(self, module, *, verdict: str, error_code: str):
        self.module = module
        self.verdict = verdict
        self.error_code = error_code
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability):
        if capability != "expert.invoke":
            raise AssertionError(capability)
        return object()

    def invoke_capability(self, _handle, request):
        self.requests.append(request)
        return {
            "protocol": self.module.PROTOCOL,
            "request_id": request["request_id"],
            "invocation_id": INVOCATION_ID,
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": self.module.PLUGIN_VERSION,
            "manifest_digest": self.module.MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": self.verdict,
            "data": {"late": True},
            "evidence_refs": ["fixture:late-terminal-output"],
            "usage": {"model_calls": 0},
            "effect_receipts": [],
            "error_code": self.error_code,
            "error_message": "terminal fence fired after dispatch",
        }


class NixBashTerminalFenceSemanticsTests(unittest.TestCase):
    def test_succeeded_result_cannot_smuggle_cancel_or_stale_error(self) -> None:
        for language, (package, module_name, class_name, payload) in CASES.items():
            for error_code in ("cancelled", "stale_generation"):
                with self.subTest(language=language, error_code=error_code):
                    module = _load_plugin(package, module_name, error_code)
                    error_class = getattr(module, f"{class_name}ExpertAdapterError")
                    runtime = TerminalFenceRuntime(
                        module,
                        verdict="succeeded",
                        error_code=error_code,
                    )
                    plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
                    plugin.start(runtime)
                    with self.assertRaisesRegex(error_class, "terminal-fence"):
                        plugin.invoke(
                            f"request-{language}-{error_code}",
                            ACTIVATION_ID,
                            "parse",
                            7,
                            11,
                            json.dumps(payload),
                        )
                    self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_stale_generation_result_cannot_publish_late_data_or_evidence(self) -> None:
        for language, (package, module_name, class_name, payload) in CASES.items():
            with self.subTest(language=language):
                module = _load_plugin(package, module_name, "stale-late-output")
                error_class = getattr(module, f"{class_name}ExpertAdapterError")
                runtime = TerminalFenceRuntime(
                    module,
                    verdict="error",
                    error_code="stale_generation",
                )
                plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
                plugin.start(runtime)
                with self.assertRaisesRegex(error_class, "terminal-fence"):
                    plugin.invoke(
                        f"request-{language}-stale-late-output",
                        ACTIVATION_ID,
                        "parse",
                        7,
                        11,
                        json.dumps(payload),
                    )
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
