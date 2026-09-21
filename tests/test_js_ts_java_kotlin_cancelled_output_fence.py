from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-cancelled-output-fence"
ACTIVATION_ID = "act:" + ("c" * 32)
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
            f"cancelled_output_fence_{module_name}", path
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
EXPERTS = (
    (JAVASCRIPT, JAVASCRIPT.JavaScriptExpertAdapterError),
    (TYPESCRIPT, TYPESCRIPT.TypeScriptExpertAdapterError),
    (JAVA, JAVA.JavaExpertAdapterError),
    (KOTLIN, KOTLIN.KotlinExpertAdapterError),
)


def _cancelled_result(module, evidence_refs: object) -> dict[str, object]:
    return {
        "protocol": module.PROTOCOL,
        "request_id": REQUEST_ID,
        "activation_id": ACTIVATION_ID,
        "expert_id": module.EXPERT_ID,
        "expert_version": module.PLUGIN_VERSION,
        "manifest_digest": module.MANIFEST_DIGEST,
        "expert_operation": "inspect",
        "resolved_registry_generation": EXPECTED_GENERATION,
        "resolved_runtime_generation": EXPECTED_GENERATION,
        "verdict": "cancelled",
        "data": {},
        "evidence_refs": evidence_refs,
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


def _validate(module, evidence_refs: object) -> None:
    module._validate_result(
        _cancelled_result(module, evidence_refs),
        request_id=REQUEST_ID,
        activation_id=ACTIVATION_ID,
        expert_operation="inspect",
        registry_generation=EXPECTED_GENERATION,
        runtime_generation=EXPECTED_GENERATION,
    )


class FourLanguageCancelledOutputFenceTests(unittest.TestCase):
    def test_canonical_empty_cancelled_projection_remains_accepted(self) -> None:
        for module, _error_type in EXPERTS:
            with self.subTest(expert_id=module.EXPERT_ID):
                _validate(module, [])

    def test_cancelled_result_rejects_late_evidence(self) -> None:
        for module, error_type in EXPERTS:
            with self.subTest(expert_id=module.EXPERT_ID):
                with self.assertRaisesRegex(
                    error_type, "cancelled-expert-output-leak"
                ):
                    _validate(module, ["evidence:late-after-root-cancel"])

    def test_cancelled_result_requires_closed_evidence_shape(self) -> None:
        for module, error_type in EXPERTS:
            with self.subTest(expert_id=module.EXPERT_ID):
                with self.assertRaisesRegex(
                    error_type, "cancelled-expert-output-leak"
                ):
                    _validate(module, "evidence:late-after-root-cancel")


if __name__ == "__main__":
    unittest.main()
