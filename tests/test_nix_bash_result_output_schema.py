from __future__ import annotations

import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path
from typing import Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-nix-bash-output-schema"
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
            f"nix_bash_result_output_schema_{module_name}", path
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
EXPERTS = (
    (NIX, NIX.NixExpertAdapterError),
    (BASH, BASH.BashExpertAdapterError),
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
    "repair.apply": {
        "effect_receipt": {},
        "postcondition_evidence": {},
    },
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
        "invocation_id": "inv:" + ("0" * 32),
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


class _MalformedHostRuntime:
    def __init__(self, module):
        self.module = module
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability: str):
        if capability != self.module.HOST_CAPABILITY:
            raise AssertionError(f"unexpected capability: {capability}")
        return "canonical-expert-host"

    def invoke_capability(self, handle, request):
        if handle != "canonical-expert-host":
            raise AssertionError("unexpected expert host handle")
        if request.get("operation") != "expert.invoke":
            raise AssertionError("must cross canonical expert.invoke")
        limits = request.get("limits")
        if type(limits) is not dict or limits.get("max_model_calls") != 0:
            raise AssertionError("pure-symbolic invocation must remain max_model_calls=0")
        self.requests.append(request)
        return _result(
            self.module,
            "inspect",
            {"renderer_fallback": "provider"},
        )


class NixBashResultOutputSchemaTests(unittest.TestCase):
    def test_package_descriptors_publish_closed_output_schema(self) -> None:
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

    def test_missing_required_outputs_fail_closed(self) -> None:
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
            "repair.apply": {"effect_receipt": [], "postcondition_evidence": {}},
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

    def test_non_success_output_cannot_smuggle_provider_shaped_data(self) -> None:
        for module, error_type in EXPERTS:
            with self.subTest(expert_id=module.EXPERT_ID):
                _validate(module, "inspect", {}, verdict="failed")
                with self.assertRaisesRegex(error_type, "invalid-expert-output"):
                    _validate(
                        module,
                        "inspect",
                        {"renderer_fallback": "provider"},
                        verdict="failed",
                    )

    def test_full_invoke_rejects_malformed_host_success_after_zero_model_dispatch(self) -> None:
        for module, error_type in EXPERTS:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _MalformedHostRuntime(module)
                plugin = module.create_plugin()
                original_validate_source_lock = module._validate_source_lock
                module._validate_source_lock = lambda: None
                try:
                    plugin.start(runtime)
                    with self.assertRaisesRegex(error_type, "invalid-expert-output"):
                        plugin.invoke(
                            request_id=REQUEST_ID,
                            activation_id=ACTIVATION_ID,
                            expert_operation="inspect",
                            expected_registry_generation=EXPECTED_GENERATION,
                            expected_runtime_generation=EXPECTED_GENERATION,
                            input_json=json.dumps(
                                {
                                    "source": "x",
                                    "source_generation": "generation-7",
                                }
                            ),
                        )
                finally:
                    module._validate_source_lock = original_validate_source_lock
                self.assertEqual(len(runtime.requests), 1)
                self.assertEqual(
                    runtime.requests[0]["limits"]["max_model_calls"],
                    0,
                )


if __name__ == "__main__":
    unittest.main()
