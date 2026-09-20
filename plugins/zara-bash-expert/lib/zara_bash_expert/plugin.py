from __future__ import annotations

import json
import math
from collections.abc import Mapping
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin


PLUGIN_VERSION = "0.1.0"
PROTOCOL = "ZARA-EXPERT/1"
EXPERT_ID = "zara:expert/bash"
HOST_CAPABILITY = "expert.invoke"
MAX_INPUT_BYTES = 65536
MAX_OUTPUT_BYTES = 65536
MAX_INPUT_DEPTH = 16
MAX_INPUT_NODES = 4096
MAX_KEY_LENGTH = 256
ALLOWED_OPERATIONS = frozenset(
    {
        "parse",
        "inspect_startup",
        "inspect_source_graph",
        "diagnose_quoting",
        "style_check",
        "check_plan",
    }
)


class BashExpertAdapterError(RuntimeError):
    """Fail-closed adapter error. No shell execution or model fallback is permitted."""


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _validate_json_tree(value: object) -> None:
    stack: list[tuple[object, int]] = [(value, 1)]
    nodes = 0
    while stack:
        current, depth = stack.pop()
        nodes += 1
        if nodes > MAX_INPUT_NODES or depth > MAX_INPUT_DEPTH:
            raise BashExpertAdapterError("input-structure-too-complex")
        if isinstance(current, dict):
            for key, child in current.items():
                if not isinstance(key, str) or len(key) > MAX_KEY_LENGTH:
                    raise BashExpertAdapterError("invalid-input-key")
                stack.append((child, depth + 1))
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current)
        elif isinstance(current, float) and not math.isfinite(current):
            raise BashExpertAdapterError("invalid-input-number")
        elif current is not None and not isinstance(current, (str, int, float, bool)):
            raise BashExpertAdapterError("invalid-input-value")


class ZaraBashExpertPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-bash-expert",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Pure-symbolic BashExpert adapter over the canonical Zara expert host",
    )

    def __init__(self) -> None:
        self._runtime: Any | None = None

    def start(self, runtime) -> None:
        # Binding is intentionally passive: discovery/start performs no source,
        # shell process, network access, expert activation, or model call.
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
            raise BashExpertAdapterError("input-must-be-json-text")
        if len(input_json.encode("utf-8")) > MAX_INPUT_BYTES:
            raise BashExpertAdapterError("input-too-large")
        try:
            value = json.loads(input_json, parse_constant=_reject_json_constant)
        except (TypeError, ValueError) as error:
            raise BashExpertAdapterError("invalid-input-json") from error
        if not isinstance(value, dict):
            raise BashExpertAdapterError("input-must-be-object")
        _validate_json_tree(value)
        return value

    def descriptor(self) -> str:
        return self._json(
            {
                "protocol": PROTOCOL,
                "expert_id": EXPERT_ID,
                "expert_version": PLUGIN_VERSION,
                "package_namespace": "zara-bash-expert",
                "name": "BashExpert",
                "description": "Deterministic Bash parse, startup, source-graph, quoting, and style inspection.",
                "source_reference": {
                    "repository": "lost-rob0t/dotfiles",
                    "path": ".zara/experts/bash",
                    "issue": 287,
                    "runtime_contract": "lost-rob0t/prolog-rlm#502",
                },
                "reasoning_kind": "symbolic",
                "operations": sorted(ALLOWED_OPERATIONS),
                "required_capabilities": [HOST_CAPABILITY],
                "possible_effects": [
                    "bash.execute",
                    "filesystem.write",
                ],
                "fallback_policy": "fail-closed-no-model",
                "resource_limits": {
                    "max_model_calls": 0,
                    "max_input_bytes": MAX_INPUT_BYTES,
                    "max_output_bytes": MAX_OUTPUT_BYTES,
                    "max_input_depth": MAX_INPUT_DEPTH,
                    "max_input_nodes": MAX_INPUT_NODES,
                },
                "availability": "inactive",
                "unavailable_reason": "activation-required",
            }
        )

    def invoke(self, activation_id: str, expert_operation: str, input_json: str = "{}") -> str:
        if expert_operation not in ALLOWED_OPERATIONS:
            raise BashExpertAdapterError("unsupported-expert-operation")
        if not isinstance(activation_id, str) or not activation_id or len(activation_id) > 256:
            raise BashExpertAdapterError("invalid-activation-id")

        payload = self._decode_input(input_json)
        runtime = self._runtime
        resolver = getattr(runtime, "resolve_capability", None)
        invoker = getattr(runtime, "invoke_capability", None)
        if not callable(resolver) or not callable(invoker):
            raise BashExpertAdapterError("expert-host-composition-unavailable")

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
        except BashExpertAdapterError:
            raise
        except Exception as error:
            raise BashExpertAdapterError("expert-host-invocation-failed") from error

        if not isinstance(result, Mapping):
            raise BashExpertAdapterError("invalid-expert-result")
        usage = result.get("usage")
        model_calls = usage.get("model_calls") if isinstance(usage, Mapping) else None
        if type(model_calls) is not int or model_calls != 0:
            raise BashExpertAdapterError("zero-model-proof-missing")
        receipts = result.get("side_effect_receipts")
        if not isinstance(receipts, list) or receipts:
            raise BashExpertAdapterError("read-only-effect-leak")

        encoded = self._json(dict(result))
        if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
            raise BashExpertAdapterError("expert-result-too-large")
        return encoded

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.descriptor,
                name="bash.expert.descriptor",
                description="Return the bounded ZARA-EXPERT/1 BashExpert descriptor without activating or executing it.",
            ),
            StructuredTool.from_function(
                func=self.invoke,
                name="bash.expert.invoke",
                description="Invoke one allowlisted read-only BashExpert symbolic operation through the canonical expert host with max_model_calls=0.",
            ),
        )


def create_plugin():
    return ZaraBashExpertPlugin()
