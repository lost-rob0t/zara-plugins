from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin


PLUGIN_VERSION = "0.1.0"
PROTOCOL = "ZARA-EXPERT/1"
EXPERT_ID = "zara:expert/nix"
HOST_CAPABILITY = "expert.invoke"
MAX_INPUT_BYTES = 65536
MAX_OUTPUT_BYTES = 65536
ALLOWED_OPERATIONS = frozenset(
    {
        "parse",
        "inspect_flake",
        "inspect_module",
        "inspect_home_manager",
        "style_check",
        "check_plan",
    }
)


class NixExpertAdapterError(RuntimeError):
    """Fail-closed adapter error. No provider/model fallback is permitted."""


class ZaraNixExpertPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-nix-expert",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Pure-symbolic NixExpert adapter over the canonical Zara expert host",
    )

    def __init__(self) -> None:
        self._runtime: Any | None = None

    def start(self, runtime) -> None:
        # Binding is intentionally passive: discovery/start performs no expert
        # activation, Nix evaluation, process execution, network I/O, or model call.
        self._runtime = runtime
        return None

    def stop(self) -> None:
        self._runtime = None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _decode_input(input_json: str) -> dict[str, Any]:
        if not isinstance(input_json, str):
            raise NixExpertAdapterError("input-must-be-json-text")
        if len(input_json.encode("utf-8")) > MAX_INPUT_BYTES:
            raise NixExpertAdapterError("input-too-large")
        try:
            value = json.loads(input_json)
        except (TypeError, ValueError) as error:
            raise NixExpertAdapterError("invalid-input-json") from error
        if not isinstance(value, dict):
            raise NixExpertAdapterError("input-must-be-object")
        return value

    def descriptor(self) -> str:
        return self._json(
            {
                "protocol": PROTOCOL,
                "expert_id": EXPERT_ID,
                "expert_version": PLUGIN_VERSION,
                "package_namespace": "zara-nix-expert",
                "name": "NixExpert",
                "description": "Deterministic Nix, flake, module, and Home Manager inspection.",
                "source_reference": {
                    "repository": "lost-rob0t/dotfiles",
                    "path": ".zara/experts/nix",
                    "issue": 286,
                    "runtime_contract": "lost-rob0t/prolog-rlm#503",
                },
                "reasoning_kind": "symbolic",
                "operations": sorted(ALLOWED_OPERATIONS),
                "required_capabilities": [HOST_CAPABILITY],
                "possible_effects": [
                    "nix.eval",
                    "nix.check",
                    "nix.build",
                    "home-manager.switch",
                ],
                "fallback_policy": "fail-closed-no-model",
                "resource_limits": {
                    "max_model_calls": 0,
                    "max_input_bytes": MAX_INPUT_BYTES,
                    "max_output_bytes": MAX_OUTPUT_BYTES,
                },
                "availability": "inactive",
                "unavailable_reason": "activation-required",
            }
        )

    def invoke(self, activation_id: str, expert_operation: str, input_json: str = "{}") -> str:
        if expert_operation not in ALLOWED_OPERATIONS:
            raise NixExpertAdapterError("unsupported-expert-operation")
        if not isinstance(activation_id, str) or not activation_id or len(activation_id) > 256:
            raise NixExpertAdapterError("invalid-activation-id")

        payload = self._decode_input(input_json)
        runtime = self._runtime
        resolver = getattr(runtime, "resolve_capability", None)
        invoker = getattr(runtime, "invoke_capability", None)
        if not callable(resolver) or not callable(invoker):
            raise NixExpertAdapterError("expert-host-composition-unavailable")

        try:
            handle = resolver(HOST_CAPABILITY)
            result = invoker(
                handle,
                {
                    "protocol": PROTOCOL,
                    "operation": "expert.invoke",
                    "activation_id": activation_id,
                    "expert_id": EXPERT_ID,
                    "expert_operation": expert_operation,
                    "input": payload,
                    "limits": {
                        "max_results": 32,
                        "max_output_bytes": MAX_OUTPUT_BYTES,
                        "max_model_calls": 0,
                    },
                    "effect_policy": "deny",
                },
            )
        except NixExpertAdapterError:
            raise
        except Exception as error:
            raise NixExpertAdapterError("expert-host-invocation-failed") from error

        if not isinstance(result, Mapping):
            raise NixExpertAdapterError("invalid-expert-result")
        usage = result.get("usage")
        if not isinstance(usage, Mapping) or usage.get("model_calls") != 0:
            raise NixExpertAdapterError("zero-model-proof-missing")

        encoded = self._json(dict(result))
        if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise NixExpertAdapterError("expert-result-too-large")
        return encoded

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.descriptor,
                name="nix.expert.descriptor",
                description="Return the bounded ZARA-EXPERT/1 NixExpert descriptor without activating or executing it.",
            ),
            StructuredTool.from_function(
                func=self.invoke,
                name="nix.expert.invoke",
                description="Invoke one allowlisted read-only NixExpert symbolic operation through the canonical expert host with max_model_calls=0.",
            ),
        )


def create_plugin():
    return ZaraNixExpertPlugin()
