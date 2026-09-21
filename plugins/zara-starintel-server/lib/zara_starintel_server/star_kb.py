"""StarKB service expert for agentic StarIntel operation planning and execution."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .client import StarIntelClient, StarIntelError
from .config import StarIntelConfig


PROTOCOL = "ZARA-EXPERT/1"
EXPERT_ID = "zara:expert/star-kb"
EXPERT_NAME = "StarKB"
EXPERT_VERSION = "0.2.0"
SYMBOL_KIND = "expert"
SOURCE_REFERENCE = "plugin:zara-starintel-server/star-kb"
MAX_PLAN_STEPS = 16
DEFAULT_PLAN_STEPS = 4
READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
WRITE_HINTS = frozenset(
    {
        "admin",
        "bootstrap",
        "create",
        "credential",
        "delete",
        "disable",
        "enable",
        "insert",
        "patch",
        "post",
        "put",
        "reset",
        "revoke",
        "submit",
        "update",
        "write",
    }
)
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")


def _fields(*items: tuple[str, str, bool]) -> dict[str, list[dict[str, Any]]]:
    return {
        "fields": [
            {"name": name, "type": field_type, "required": required}
            for name, field_type, required in items
        ]
    }


def _operation(
    operation_id: str,
    inputs: tuple[tuple[str, str, bool], ...],
    outputs: tuple[tuple[str, str, bool], ...],
) -> dict[str, Any]:
    return {
        "operation_id": operation_id,
        "input_schema": _fields(*inputs),
        "output_schema": _fields(*outputs),
    }


OPERATIONS = (
    _operation(
        "observe",
        (("refresh", "boolean", False),),
        (
            ("configured", "boolean", True),
            ("capabilities", "object", True),
            ("operations", "list", True),
        ),
    ),
    _operation(
        "plan",
        (
            ("goal", "string", True),
            ("max_steps", "integer", False),
            ("allow_writes", "boolean", False),
        ),
        (
            ("goal", "string", True),
            ("steps", "list", True),
            ("write_steps", "integer", True),
        ),
    ),
    _operation(
        "run",
        (
            ("goal", "string", True),
            ("bindings", "object", False),
            ("max_steps", "integer", False),
            ("allow_writes", "boolean", False),
            ("dry_run", "boolean", False),
            ("require_idempotency", "boolean", False),
        ),
        (
            ("plan", "object", True),
            ("executed", "list", True),
            ("completed", "boolean", True),
        ),
    ),
    _operation(
        "explain",
        (("goal", "string", True), ("max_steps", "integer", False)),
        (
            ("goal", "string", True),
            ("steps", "list", True),
            ("explanation", "string", True),
        ),
    ),
)


def _digest_material() -> str:
    material = json.dumps(
        {
            "protocol": PROTOCOL,
            "expert_id": EXPERT_ID,
            "version": EXPERT_VERSION,
            "source": SOURCE_REFERENCE,
            "operations": OPERATIONS,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


MANIFEST_DIGEST = _digest_material()


def descriptor(*, available: bool) -> dict[str, Any]:
    item: dict[str, Any] = {
        "protocol": PROTOCOL,
        "expert_id": EXPERT_ID,
        "expert_version": EXPERT_VERSION,
        "package_namespace": "zara-starintel-server",
        "manifest_digest": MANIFEST_DIGEST,
        "name": EXPERT_NAME,
        "description": (
            "Service-backed StarIntel expert for live capability discovery, bounded "
            "operation planning, evidence gathering, and policy-fenced execution."
        ),
        "source_reference": SOURCE_REFERENCE,
        "reasoning_kind": "service",
        "operations": list(OPERATIONS),
        "applicability": {
            "keywords": [
                "starintel",
                "star-kb",
                "osint",
                "socmint",
                "investigation",
                "target",
                "document",
                "actor",
                "evidence",
            ]
        },
        "required_capabilities": ["star-kb.run"],
        "possible_effects": ["network_egress"],
        "supported_engines": [],
        "supported_platforms": ["linux"],
        "fallback_policy": "fail_closed",
        "delegation_policy": "children",
        "resource_limits": {
            "timeout_ms": 60000,
            "max_results": 128,
            "max_output_bytes": 1048576,
            "max_model_calls": 0,
        },
        "registry_generation": 0,
        "availability": "ready" if available else "unavailable",
    }
    if not available:
        item["unavailable_reason"] = "starintel-server-unconfigured"
    return item


def _positive_int(value: int, *, name: str, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise StarIntelError(f"{name} must be an integer")
    if not 1 <= value <= maximum:
        raise StarIntelError(f"{name} must be between 1 and {maximum}")
    return value


def _tokens(value: object) -> frozenset[str]:
    text = str(value).lower()
    tokens = set(TOKEN_RE.findall(text))
    tokens.update(re.findall(r"[a-z0-9]+", text))
    return frozenset(tokens)


def _operation_id(operation: Mapping[str, Any]) -> str:
    value = operation.get("operation_id")
    return value if isinstance(value, str) else ""


def _method(operation: Mapping[str, Any]) -> str:
    for key in ("method", "http_method"):
        value = operation.get(key)
        if isinstance(value, str):
            method = value.upper()
            if method in READ_METHODS | WRITE_METHODS:
                return method
    methods = operation.get("methods")
    if isinstance(methods, (list, tuple)) and len(methods) == 1:
        value = methods[0]
        if isinstance(value, str):
            method = value.upper()
            if method in READ_METHODS | WRITE_METHODS:
                return method
    return "UNKNOWN"


def _path(operation: Mapping[str, Any]) -> str:
    value = operation.get("path")
    return value if isinstance(value, str) else ""


def _is_write(operation: Mapping[str, Any]) -> bool:
    method = _method(operation)
    if method in WRITE_METHODS:
        return True
    if method in READ_METHODS:
        return False
    return bool(_tokens(_operation_id(operation)) & WRITE_HINTS)


def _search_text(operation: Mapping[str, Any]) -> str:
    fields: list[str] = []
    for key in (
        "operation_id",
        "method",
        "http_method",
        "path",
        "summary",
        "description",
        "authority",
    ):
        value = operation.get(key)
        if isinstance(value, str):
            fields.append(value)
    for key in ("tags", "scopes", "authorities"):
        value = operation.get(key)
        if isinstance(value, (list, tuple)):
            fields.extend(str(item) for item in value if isinstance(item, str))
    return " ".join(fields)


def _score(goal: str, operation: Mapping[str, Any]) -> int:
    goal_tokens = _tokens(goal)
    if not goal_tokens:
        return 0
    operation_tokens = _tokens(_search_text(operation))
    overlap = goal_tokens & operation_tokens
    score = len(overlap) * 4

    operation_id = _operation_id(operation).lower()
    goal_lower = goal.lower()
    if operation_id and operation_id in goal_lower:
        score += 20

    path = _path(operation).lower()
    if path and any(token in path for token in goal_tokens):
        score += 3

    for token in goal_tokens:
        if operation_id.startswith(token + ".") or operation_id.endswith("." + token):
            score += 2
    return score


def _safe_operation(operation: Mapping[str, Any], score: int) -> dict[str, Any]:
    safe: dict[str, Any] = {
        "operation_id": _operation_id(operation),
        "method": _method(operation),
        "path": _path(operation),
        "score": score,
        "write": _is_write(operation),
    }
    for key in ("authority", "scopes", "summary", "description"):
        value = operation.get(key)
        if isinstance(value, (str, list, tuple, dict, bool, int, float)) or value is None:
            safe[key] = value
    return safe


class StarKB:
    """Bounded deterministic agent layer over live StarIntel discovery."""

    def __init__(self, client: StarIntelClient, config: StarIntelConfig) -> None:
        self._client = client
        self._config = config

    @property
    def available(self) -> bool:
        return bool(self._config.enabled and self._config.base_url)

    def observe(self, *, refresh: bool = False) -> dict[str, Any]:
        if not self.available:
            return {
                "configured": False,
                "capabilities": {},
                "operations": [],
            }
        operations = self._client.operations(refresh=refresh)
        return {
            "configured": True,
            "capabilities": self._client.capabilities(),
            "operations": operations,
        }

    def plan(
        self,
        goal: str,
        *,
        max_steps: int = DEFAULT_PLAN_STEPS,
        allow_writes: bool = False,
        refresh: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(goal, str) or not goal.strip():
            raise StarIntelError("goal must be non-empty text")
        step_limit = _positive_int(max_steps, name="max_steps", maximum=MAX_PLAN_STEPS)
        operations = self._client.operations(refresh=refresh)
        scored: list[tuple[int, str, Mapping[str, Any]]] = []
        for raw in operations:
            if not isinstance(raw, Mapping):
                continue
            operation_id = _operation_id(raw)
            if not operation_id:
                continue
            if _is_write(raw) and not allow_writes:
                continue
            score = _score(goal, raw)
            if score > 0:
                scored.append((score, operation_id, raw))

        scored.sort(key=lambda item: (-item[0], item[1]))
        steps = [_safe_operation(raw, score) for score, _name, raw in scored[:step_limit]]
        return {
            "schema": "star-kb-plan-v1",
            "goal": goal.strip(),
            "max_steps": step_limit,
            "allow_writes": bool(allow_writes),
            "steps": steps,
            "write_steps": sum(1 for step in steps if step["write"]),
            "matched": bool(steps),
        }

    def explain(self, goal: str, *, max_steps: int = DEFAULT_PLAN_STEPS) -> dict[str, Any]:
        plan = self.plan(goal, max_steps=max_steps, allow_writes=False)
        if plan["steps"]:
            names = ", ".join(step["operation_id"] for step in plan["steps"])
            explanation = (
                "StarKB ranked live StarIntel operations by lexical overlap with the "
                f"goal while excluding write-capable operations: {names}."
            )
        else:
            explanation = (
                "No read-only live StarIntel operation had enough lexical evidence to "
                "form a plan. Refresh discovery or supply a more specific goal."
            )
        return {
            "goal": plan["goal"],
            "steps": plan["steps"],
            "explanation": explanation,
        }

    def run(
        self,
        goal: str,
        *,
        bindings: Mapping[str, Any] | None = None,
        max_steps: int = DEFAULT_PLAN_STEPS,
        allow_writes: bool = False,
        dry_run: bool = True,
        require_idempotency: bool = True,
    ) -> dict[str, Any]:
        plan = self.plan(
            goal,
            max_steps=max_steps,
            allow_writes=allow_writes,
            refresh=True,
        )
        resolved_bindings = dict(bindings or {})
        unknown_bindings = set(resolved_bindings) - {
            step["operation_id"] for step in plan["steps"]
        }
        if unknown_bindings:
            raise StarIntelError(
                "bindings contain operations outside the admitted plan: "
                + ", ".join(sorted(unknown_bindings))
            )

        if dry_run:
            return {
                "schema": "star-kb-run-v1",
                "plan": plan,
                "executed": [],
                "completed": bool(plan["steps"]),
                "dry_run": True,
            }

        executed: list[dict[str, Any]] = []
        completed = bool(plan["steps"])
        for step in plan["steps"]:
            operation_id = step["operation_id"]
            write = bool(step["write"])
            if write and not allow_writes:
                executed.append(
                    {
                        "operation_id": operation_id,
                        "ok": False,
                        "blocked": True,
                        "reason": "write-operation-not-admitted",
                    }
                )
                completed = False
                break

            raw_binding = resolved_bindings.get(operation_id, {})
            if not isinstance(raw_binding, Mapping):
                raise StarIntelError(f"binding for {operation_id} must be an object")
            binding = dict(raw_binding)
            allowed_fields = {"path_parameters", "query", "body", "headers"}
            unknown = set(binding) - allowed_fields
            if unknown:
                raise StarIntelError(
                    f"binding for {operation_id} has unknown fields: {sorted(unknown)!r}"
                )

            headers = binding.get("headers") or {}
            if not isinstance(headers, Mapping):
                raise StarIntelError(f"headers for {operation_id} must be an object")
            if write and require_idempotency:
                lowered = {str(key).lower() for key in headers}
                if "idempotency-key" not in lowered:
                    executed.append(
                        {
                            "operation_id": operation_id,
                            "ok": False,
                            "blocked": True,
                            "reason": "write-operation-requires-idempotency-key",
                        }
                    )
                    completed = False
                    break

            try:
                result = self._client.call_operation(
                    operation_id,
                    path_parameters=dict(binding.get("path_parameters") or {}),
                    query=dict(binding.get("query") or {}),
                    body=binding.get("body"),
                    headers=dict(headers),
                )
            except StarIntelError as error:
                executed.append(
                    {
                        "operation_id": operation_id,
                        "ok": False,
                        "error": str(error),
                    }
                )
                completed = False
                break

            executed.append(
                {
                    "operation_id": operation_id,
                    "ok": bool(result.get("ok")),
                    "status": result.get("status"),
                    "correlation_id": result.get("correlation_id"),
                    "result": result,
                }
            )
            if not result.get("ok"):
                completed = False
                break

        return {
            "schema": "star-kb-run-v1",
            "plan": plan,
            "executed": executed,
            "completed": completed and len(executed) == len(plan["steps"]),
            "dry_run": False,
        }


__all__ = [
    "EXPERT_ID",
    "EXPERT_VERSION",
    "MANIFEST_DIGEST",
    "SOURCE_REFERENCE",
    "StarKB",
    "descriptor",
]
