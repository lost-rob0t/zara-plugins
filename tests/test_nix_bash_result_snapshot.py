from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "req-nix-bash-result-snapshot"
ACTIVATION_ID = "act:" + ("a" * 32)
INVOCATION_ID = "inv:" + ("b" * 32)
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
            f"nix_bash_result_snapshot_{module_name}",
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

CASES = (
    (NIX, NIX.NixExpertAdapterError, "{ x = 1; }"),
    (BASH, BASH.BashExpertAdapterError, "x=1"),
)


def _expected_provenance_ref(module) -> str:
    payload = {
        "expert_id": module.EXPERT_ID,
        "expert_version": module.PLUGIN_VERSION,
        "manifest_digest": module.MANIFEST_DIGEST,
        "source_reference": module.SOURCE_REFERENCE,
        "upstream_contract": module.UPSTREAM_CONTRACT,
        "zara_contract": (
            f"{module.ZARA_CONTRACT_REPOSITORY}#{module.ZARA_CONTRACT_ISSUE}"
        ),
        "zara_schema_pr": module.ZARA_CONTRACT_SCHEMA_PR,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "evidence:expert-provenance:sha256:" + hashlib.sha256(encoded).hexdigest()


class _Runtime:
    def __init__(self, module) -> None:
        self.module = module
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability: str) -> str:
        if capability != "expert.invoke":
            raise AssertionError(f"unexpected capability: {capability}")
        return capability

    def invoke_capability(self, handle: str, request: dict[str, object]):
        if handle != "expert.invoke":
            raise AssertionError(f"unexpected handle: {handle}")
        self.requests.append(request)
        if request["limits"]["max_model_calls"] != 0:  # type: ignore[index]
            raise AssertionError("pure-symbolic invocation must keep max_model_calls=0")
        return {
            "protocol": self.module.PROTOCOL,
            "request_id": request["request_id"],
            "invocation_id": INVOCATION_ID,
            "activation_id": request["activation_id"],
            "expert_id": self.module.EXPERT_ID,
            "expert_version": self.module.PLUGIN_VERSION,
            "manifest_digest": self.module.MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "succeeded",
            "data": {"result": {"kind": "symbolic"}},
            "evidence_refs": ["fixture:evidence"],
            "usage": {"model_calls": 0},
            "effect_receipts": [],
            "error_code": None,
            "error_message": "",
            "replayed": False,
        }


def _invoke(module, runtime: _Runtime, source: str) -> str:
    plugin = module.create_plugin()
    plugin.start(runtime)
    return plugin.invoke(
        request_id=REQUEST_ID,
        activation_id=ACTIVATION_ID,
        expert_operation=EXPERT_OPERATION,
        expected_registry_generation=EXPECTED_GENERATION,
        expected_runtime_generation=EXPECTED_GENERATION,
        input_json=json.dumps(
            {"source": source, "source_generation": "fixture:result-snapshot:1"}
        ),
    )


class NixBashResultSnapshotTests(unittest.TestCase):
    def test_post_validation_mutation_fails_closed_before_projection(self) -> None:
        for module, error_type, source in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _Runtime(module)
                original_validate = module._validate_result
                calls = 0

                def validate_then_poison(result, **kwargs):
                    nonlocal calls
                    calls += 1
                    original_validate(result, **kwargs)
                    if calls == 1:
                        result["usage"]["model_calls"] = 1
                        result["usage"]["provider_calls"] = 1
                        result["effect_receipts"].append({"effect": "forbidden"})
                        result["evidence_refs"].append("fixture:late-poison")
                        result["data"]["result"]["provider"] = "forbidden"

                module._validate_result = validate_then_poison
                try:
                    with self.assertRaisesRegex(error_type, "unknown-expert-usage-field"):
                        _invoke(module, runtime, source)
                finally:
                    module._validate_result = original_validate

                self.assertGreaterEqual(calls, 2)
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_serialized_success_binds_verified_provenance_snapshot(self) -> None:
        for module, _error_type, source in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                expected_ref = _expected_provenance_ref(module)
                runtime = _Runtime(module)
                encoded = _invoke(module, runtime, source)
                projected = json.loads(encoded)

                self.assertEqual(
                    projected["evidence_refs"],
                    ["fixture:evidence", expected_ref],
                )
                self.assertEqual(projected["manifest_digest"], module.MANIFEST_DIGEST)
                self.assertEqual(projected["usage"], {"model_calls": 0})
                self.assertEqual(projected["effect_receipts"], [])
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

                original_source = module.SOURCE_REFERENCE
                original_upstream = module.UPSTREAM_CONTRACT
                try:
                    module.SOURCE_REFERENCE = original_source + "-newer"
                    module.UPSTREAM_CONTRACT = original_upstream + "-newer"
                    recovered = json.loads(encoded)
                    self.assertEqual(
                        recovered["evidence_refs"],
                        ["fixture:evidence", expected_ref],
                    )
                finally:
                    module.SOURCE_REFERENCE = original_source
                    module.UPSTREAM_CONTRACT = original_upstream

    def test_unmutated_result_remains_zero_model_and_read_only(self) -> None:
        for module, _error_type, source in CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                runtime = _Runtime(module)
                projected = json.loads(_invoke(module, runtime, source))
                self.assertEqual(projected["usage"], {"model_calls": 0})
                self.assertEqual(projected["effect_receipts"], [])
                self.assertEqual(
                    projected["evidence_refs"],
                    ["fixture:evidence", _expected_provenance_ref(module)],
                )
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
