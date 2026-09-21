from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from typing import Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-output-schema"
ACTIVATION_ID = "act:" + ("e" * 32)
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
            f"result_output_schema_{module_name}", path
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

VALID_OUTPUTS: Mapping[str, dict[str, object]] = {
    "match": {"applicable": True, "evidence_refs": [], "explanation_refs": []},
    "inspect": {"result": {}, "evidence_refs": [], "explanation_refs": []},
    "diagnose": {"diagnostics": [], "evidence_refs": [], "explanation_refs": []},
    "repair.preview": {"repair": {}, "evidence_refs": [], "explanation_refs": []},
    "repair.verify": {
        "verified": False,
        "postcondition_evidence": {},
        "evidence_refs": [],
        "explanation_refs": [],
    },
    "style.rules": {
        "style_rules": [],
        "style_provenance": [],
        "evidence_refs": [],
        "explanation_refs": [],
    },
    "explain": {"explanation": {}, "evidence_refs": [], "explanation_refs": []},
}


def _result(
    module,
    operation: str,
    data: object,
    *,
    verdict: str = "succeeded",
) -> dict[str, object]:
    return {
        "protocol": module.PROTOCOL,
        "request_id": REQUEST_ID,
        "activation_id": ACTIVATION_ID,
        "expert_id": module.EXPERT_ID,
        "expert_version": module.PLUGIN_VERSION,
        "manifest_digest": module.MANIFEST_DIGEST,
        "expert_operation": operation,
        "resolved_registry_generation": EXPECTED_GENERATION,
        "resolved_runtime_generation": EXPECTED_GENERATION,
        "verdict": verdict,
        "data": data,
        "evidence_refs": [],
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


def _validate(
    module,
    operation: str,
    data: object,
    *,
    verdict: str = "succeeded",
) -> None:
    module._validate_result(
        _result(module, operation, data, verdict=verdict),
        request_id=REQUEST_ID,
        activation_id=ACTIVATION_ID,
        expert_operation=operation,
        registry_generation=EXPECTED_GENERATION,
        runtime_generation=EXPECTED_GENERATION,
    )


class FourLanguageResultOutputSchemaTests(unittest.TestCase):
    def test_all_package_descriptors_publish_the_closed_canonical_output_schema(self) -> None:
        for module, _error_type in EXPERTS:
            self.assertEqual(set(module.OPERATION_OUTPUT_FIELDS), set(VALID_OUTPUTS))
            for operation in VALID_OUTPUTS:
                with self.subTest(expert_id=module.EXPERT_ID, operation=operation):
                    descriptor = module._operation_descriptor(operation)
                    self.assertEqual(
                        descriptor["output_schema"]["fields"],
                        [dict(field) for field in module.OPERATION_OUTPUT_FIELDS[operation]],
                    )

    def test_canonical_declared_outputs_remain_accepted(self) -> None:
        for module, _error_type in EXPERTS:
            for operation, data in VALID_OUTPUTS.items():
                with self.subTest(expert_id=module.EXPERT_ID, operation=operation):
                    _validate(module, operation, dict(data))

    def test_non_object_data_fails_closed(self) -> None:
        for module, error_type in EXPERTS:
            with self.subTest(expert_id=module.EXPERT_ID):
                with self.assertRaisesRegex(error_type, "invalid-expert-output"):
                    _validate(module, "inspect", [])

    def test_missing_required_output_fails_closed(self) -> None:
        for module, error_type in EXPERTS:
            for operation in VALID_OUTPUTS:
                with self.subTest(expert_id=module.EXPERT_ID, operation=operation):
                    with self.assertRaisesRegex(error_type, "invalid-expert-output"):
                        _validate(module, operation, {})

    def test_wrong_declared_output_types_fail_closed(self) -> None:
        malformed = {
            "match": {"applicable": 1},
            "inspect": {"result": []},
            "diagnose": {"diagnostics": {}},
            "repair.preview": {"repair": []},
            "repair.verify": {"verified": 1, "postcondition_evidence": {}},
            "style.rules": {"style_rules": {}, "style_provenance": []},
            "explain": {"explanation": []},
        }
        for module, error_type in EXPERTS:
            for operation, data in malformed.items():
                with self.subTest(expert_id=module.EXPERT_ID, operation=operation):
                    with self.assertRaisesRegex(error_type, "invalid-expert-output"):
                        _validate(module, operation, data)

    def test_optional_lineage_fields_must_be_lists(self) -> None:
        for module, error_type in EXPERTS:
            for field in ("evidence_refs", "explanation_refs"):
                data = dict(VALID_OUTPUTS["inspect"])
                data[field] = "not-a-list"
                with self.subTest(expert_id=module.EXPERT_ID, field=field):
                    with self.assertRaisesRegex(error_type, "invalid-expert-output"):
                        _validate(module, "inspect", data)

    def test_unknown_output_fields_fail_closed(self) -> None:
        for module, error_type in EXPERTS:
            data = dict(VALID_OUTPUTS["inspect"])
            data["renderer_fallback"] = "provider"
            with self.subTest(expert_id=module.EXPERT_ID):
                with self.assertRaisesRegex(error_type, "invalid-expert-output"):
                    _validate(module, "inspect", data)

    def test_empty_cancelled_output_is_accepted_but_provider_shaped_cancelled_data_is_not(self) -> None:
        for module, error_type in EXPERTS:
            with self.subTest(expert_id=module.EXPERT_ID):
                _validate(module, "inspect", {}, verdict="cancelled")
                with self.assertRaisesRegex(
                    error_type, "cancelled-expert-output-leak"
                ):
                    _validate(
                        module,
                        "inspect",
                        {"renderer_fallback": "provider"},
                        verdict="cancelled",
                    )


if __name__ == "__main__":
    unittest.main()
