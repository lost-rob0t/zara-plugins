from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-result-json-evidence"
ACTIVATION_ID = "act:" + ("d" * 32)
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
            f"result_json_evidence_{module_name}",
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


JAVASCRIPT = _load_plugin("zara-javascript-expert", "zara_javascript_expert")
TYPESCRIPT = _load_plugin("zara-typescript-expert", "zara_typescript_expert")
JAVA = _load_plugin("zara-java-expert", "zara_java_expert")
KOTLIN = _load_plugin("zara-kotlin-expert", "zara_kotlin_expert")


CASES = (
    (JAVASCRIPT, JAVASCRIPT.JavaScriptExpertAdapterError),
    (TYPESCRIPT, TYPESCRIPT.TypeScriptExpertAdapterError),
    (JAVA, JAVA.JavaExpertAdapterError),
    (KOTLIN, KOTLIN.KotlinExpertAdapterError),
)


class _CanonicalLookingEvidence:
    def __str__(self) -> str:
        return "evidence:language:sha256:" + ("0" * 64)


def _result(module, *, data: object, evidence_refs: object) -> dict[str, object]:
    return {
        "protocol": module.PROTOCOL,
        "request_id": REQUEST_ID,
        "invocation_id": "inv:" + ("0" * 32),
        "activation_id": ACTIVATION_ID,
        "expert_id": module.EXPERT_ID,
        "expert_version": module.PLUGIN_VERSION,
        "manifest_digest": module.MANIFEST_DIGEST,
        "expert_operation": EXPERT_OPERATION,
        "resolved_registry_generation": EXPECTED_GENERATION,
        "resolved_runtime_generation": EXPECTED_GENERATION,
        "verdict": "succeeded",
        "data": data,
        "evidence_refs": evidence_refs,
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


def _validate(module, result: dict[str, object]) -> None:
    module._validate_result(
        result,
        request_id=REQUEST_ID,
        activation_id=ACTIVATION_ID,
        expert_operation=EXPERT_OPERATION,
        registry_generation=EXPECTED_GENERATION,
        runtime_generation=EXPECTED_GENERATION,
    )


class ResultJsonEvidenceFenceTests(unittest.TestCase):
    def test_non_json_success_data_fails_closed_before_projection(self) -> None:
        invalid_values = (
            {"not-json"},
            b"not-json",
            float("nan"),
            float("inf"),
            float("-inf"),
            {1: "non-string-key"},
        )

        for module, error_type in CASES:
            for invalid in invalid_values:
                with self.subTest(expert_id=module.EXPERT_ID, value=repr(invalid)):
                    with self.assertRaisesRegex(error_type, "invalid-expert-data-json"):
                        _validate(
                            module,
                            _result(
                                module,
                                data={"result": {"value": invalid}},
                                evidence_refs=[],
                            ),
                        )

    def test_cyclic_success_data_fails_closed_before_projection(self) -> None:
        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic

        for module, error_type in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                with self.assertRaisesRegex(error_type, "invalid-expert-data-json"):
                    _validate(
                        module,
                        _result(
                            module,
                            data={"result": cyclic},
                            evidence_refs=[],
                        ),
                    )

    def test_success_evidence_requires_bounded_exact_strings(self) -> None:
        invalid_evidence = (
            "evidence:not-a-sequence",
            [""],
            [_CanonicalLookingEvidence()],
            ["x" * 4097],
        )

        for module, error_type in CASES:
            for evidence_refs in invalid_evidence:
                with self.subTest(
                    expert_id=module.EXPERT_ID,
                    evidence_refs=repr(evidence_refs),
                ):
                    with self.assertRaisesRegex(error_type, "invalid-expert-evidence"):
                        _validate(
                            module,
                            _result(
                                module,
                                data={"result": {}},
                                evidence_refs=evidence_refs,
                            ),
                        )


if __name__ == "__main__":
    unittest.main()
