from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable, Mapping

from .domain import ExpertError, ExpertHost


PROTOCOL = "ZARA-EXPERT/1"
EXPERT_ID = "zara:expert/dotfiles"
EXPERT_KEY = "dotfiles"
NAMESPACE = "dotfiles-expert"
SOURCE_OWNER = "lost-rob0t/dotfiles#282"
SOURCE_REFERENCE = "dotfiles:.zara/experts/dotfiles"
MAX_MODEL_CALLS = 0

_REGISTERED_PREDICATES: Mapping[str, int] = {
    "nix_path": 1,
    "bash_path": 1,
    "home_manager_owned_path": 1,
}


def registered_predicates() -> dict[str, int]:
    return dict(_REGISTERED_PREDICATES)


def _fields(*items: tuple[str, str, bool]) -> dict[str, list[dict[str, Any]]]:
    return {
        "fields": [
            {"name": name, "type": field_type, "required": required}
            for name, field_type, required in items
        ]
    }


def _operation_schema(operation: str) -> dict[str, Any]:
    if operation == "inspect":
        return {
            "operation_id": operation,
            "input_schema": _fields(
                ("path", "string", True),
                ("source", "string", True),
                ("source_generation", "reference", True),
            ),
            "output_schema": _fields(
                ("result", "object", True),
                ("evidence_refs", "list", False),
            ),
        }
    if operation == "ownership":
        return {
            "operation_id": operation,
            "input_schema": _fields(("path", "string", True)),
            "output_schema": _fields(
                ("result", "object", True),
                ("evidence_refs", "list", False),
            ),
        }
    if operation == "explain":
        return {
            "operation_id": operation,
            "input_schema": _fields(
                ("path", "string", True),
                ("decision", "enum", True),
            ),
            "output_schema": _fields(
                ("result", "object", True),
                ("evidence_refs", "list", False),
            ),
        }
    if operation == "repair.apply":
        return {
            "operation_id": operation,
            "input_schema": _fields(
                ("repair", "object", True),
                ("expected_preimage", "string", True),
                ("source_generation", "reference", True),
            ),
            "output_schema": _fields(
                ("effect_receipt", "object", True),
                ("postcondition_evidence", "object", True),
            ),
        }
    raise ExpertError(f"unsupported DotfilesExpert operation: {operation!r}")


def dotfiles_expert_schemas() -> dict[str, dict[str, Any]]:
    return {
        operation: {
            "input_schema": _operation_schema(operation)["input_schema"],
            "output_schema": _operation_schema(operation)["output_schema"],
        }
        for operation in ("inspect", "ownership", "explain", "repair.apply")
    }


def _source_files(paths: Iterable[str | Path]) -> tuple[Path, ...]:
    files = tuple(Path(path).expanduser().resolve() for path in paths)
    if not files:
        raise ExpertError("DotfilesExpert source list must not be empty")
    for path in files:
        if not path.is_file():
            raise ExpertError(f"DotfilesExpert source is not a regular file: {path}")
    return files


def register_dotfiles_expert(host: ExpertHost, source_files: Iterable[str | Path]) -> None:
    """Register only the fixed producer ABI through the existing expert host."""

    files = _source_files(source_files)
    host.preflight_registration(NAMESPACE, files, predicates=_REGISTERED_PREDICATES)
    host.register(NAMESPACE, files, predicates=_REGISTERED_PREDICATES)


def _query_matches(host: ExpertHost, predicate: str, path: str) -> tuple[str, ...]:
    result = host.query(NAMESPACE, predicate, [path])
    if result.get("ok") is not True:
        raise ExpertError(f"DotfilesExpert predicate {predicate!r} failed")
    raw = result.get("results")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, list):
        raise ExpertError("DotfilesExpert host returned malformed results")
    return tuple(str(item) for item in raw)


def invoke_dotfiles_operation(
    host: ExpertHost,
    operation: str,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ExpertError("DotfilesExpert input must be an object")
    schemas = dotfiles_expert_schemas()
    schema = schemas.get(operation)
    if schema is None:
        raise ExpertError(f"unsupported DotfilesExpert operation: {operation!r}")
    fields = schema["input_schema"]["fields"]
    allowed = {field["name"] for field in fields}
    unknown = set(payload) - allowed
    if unknown:
        raise ExpertError(f"unknown DotfilesExpert input field: {sorted(unknown)[0]!r}")
    missing = [
        field["name"]
        for field in fields
        if field["required"] and field["name"] not in payload
    ]
    if missing:
        raise ExpertError(f"missing DotfilesExpert input field: {missing[0]!r}")

    if operation == "repair.apply":
        raise ExpertError(
            "repair.apply requires Zara's canonical typed edit/effect path; "
            "DotfilesExpert registration grants no write authority"
        )

    path = payload.get("path")
    if not isinstance(path, str) or not path:
        raise ExpertError("DotfilesExpert path must be non-empty text")

    evidence: list[str] = []
    data: dict[str, Any] = {"path": path}
    verdict = "unknown"
    explanation: list[str] = []

    if operation in {"inspect", "explain"}:
        nix = _query_matches(host, "nix_path", path)
        bash = _query_matches(host, "bash_path", path)
        if nix:
            evidence.extend(nix)
        if bash:
            evidence.extend(bash)
        if nix and bash:
            data["reason"] = "ambiguous-specialist"
            explanation.append("DotfilesExpert found conflicting registered specialists")
        elif nix:
            data.update(language="nix", specialist_expert_id="zara:expert/nix")
            verdict = "succeeded"
            explanation.append("DotfilesExpert selected the registered NixExpert")
        elif bash:
            data.update(language="bash", specialist_expert_id="zara:expert/bash")
            verdict = "succeeded"
            explanation.append("DotfilesExpert selected the registered BashExpert")
        else:
            data["reason"] = "unsupported-path"
            explanation.append("DotfilesExpert has no registered specialist for this path")

        if operation == "explain":
            decision = payload.get("decision")
            if decision != "specialist":
                raise ExpertError("DotfilesExpert explain currently supports decision='specialist'")

    elif operation == "ownership":
        owned = _query_matches(host, "home_manager_owned_path", path)
        evidence.extend(owned)
        if owned:
            verdict = "succeeded"
            data["owner"] = "home_manager"
            explanation.append("DotfilesExpert proved ownership from the durable project KB")
        else:
            data["reason"] = "ownership-unknown"
            explanation.append("DotfilesExpert has no ownership proof for this path")

    return {
        "protocol": PROTOCOL,
        "expert_id": EXPERT_ID,
        "operation": operation,
        "source_reference": SOURCE_REFERENCE,
        "verdict": verdict,
        "data": data,
        "evidence": evidence,
        "explanation": explanation,
        "model_calls": MAX_MODEL_CALLS,
        "effect_receipts": [],
    }


def _manifest_digest() -> str:
    material = "|".join(
        (
            PROTOCOL,
            EXPERT_ID,
            SOURCE_OWNER,
            SOURCE_REFERENCE,
            ",".join(f"{name}/{arity}" for name, arity in sorted(_REGISTERED_PREDICATES.items())),
            "inspect:delegates-to-canonical-specialist",
            "repair.apply:canonical-zara-effect-path",
            f"max_model_calls={MAX_MODEL_CALLS}",
        )
    )
    return f"sha256:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def descriptor(*, available: bool) -> dict[str, Any]:
    item: dict[str, Any] = {
        "protocol": PROTOCOL,
        "expert_id": EXPERT_ID,
        "expert_version": "1",
        "package_namespace": "zara-expert",
        "manifest_digest": _manifest_digest(),
        "name": "DotfilesExpert",
        "description": (
            "Pure-symbolic adapter for Dotfiles-owned project reasoning, provenance, "
            "ownership and registered specialist delegation."
        ),
        "source_reference": SOURCE_REFERENCE,
        "reasoning_kind": "symbolic",
        "operations": [
            _operation_schema(operation)
            for operation in ("inspect", "ownership", "explain", "repair.apply")
        ],
        "applicability": {"keywords": ["dotfiles", "nix", "bash", "configuration"]},
        "required_capabilities": [],
        "possible_effects": ["filesystem_write"],
        "supported_engines": ["swipl"],
        "supported_platforms": [],
        "fallback_policy": "fail_closed",
        "delegation_policy": "children",
        "resource_limits": {"max_model_calls": MAX_MODEL_CALLS},
        "registry_generation": 0,
        "availability": "available" if available else "absent",
    }
    if not available:
        item["unavailable_reason"] = "source-unavailable"
    return item


__all__ = [
    "EXPERT_ID",
    "MAX_MODEL_CALLS",
    "NAMESPACE",
    "PROTOCOL",
    "SOURCE_OWNER",
    "SOURCE_REFERENCE",
    "descriptor",
    "dotfiles_expert_schemas",
    "invoke_dotfiles_operation",
    "register_dotfiles_expert",
    "registered_predicates",
]
