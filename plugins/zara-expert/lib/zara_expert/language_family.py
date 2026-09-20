from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .domain import ExpertError, ExpertHost


PROTOCOL = "ZARA-EXPERT/1"
SYMBOL_KIND = "expert"
SOURCE_OWNER = "lost-rob0t/dotfiles#292"
MAX_MODEL_CALLS = 0
RESERVED_HOST_INPUT_FIELDS = frozenset({"expert_operation"})
_BASE_DESCRIPTOR_KEYS = frozenset({"prolog", "python", "nim"})


@dataclass(frozen=True)
class OperationBinding:
    predicate: str
    arity: int
    mode: str = "query"


@dataclass(frozen=True)
class LanguageExpertSpec:
    key: str
    expert_id: str
    namespace: str
    name: str
    language: str
    extensions: tuple[str, ...]
    applicability_keywords: tuple[str, ...]
    source_reference: str
    upstream_issue: str


_OPERATION_BINDINGS: Mapping[str, OperationBinding] = {
    "match": OperationBinding("language_applicable", 3),
    "inspect": OperationBinding("language_evidence", 3),
    "diagnose": OperationBinding("language_diagnostic", 3),
    "repair.preview": OperationBinding("language_repair_preview", 4),
    "repair.verify": OperationBinding("language_repair_verify", 4),
    "style.rules": OperationBinding("language_style_rules", 3),
    "explain": OperationBinding("language_explanation", 3, mode="explain"),
}

_PREDICATES: Mapping[str, int] = {
    binding.predicate: binding.arity for binding in _OPERATION_BINDINGS.values()
}

_SPECS: tuple[LanguageExpertSpec, ...] = (
    LanguageExpertSpec(
        key="prolog",
        expert_id="zara:expert/prolog",
        namespace="prolog-expert",
        name="PrologExpert",
        language="prolog",
        extensions=(".pl", ".pro", ".prolog"),
        applicability_keywords=("prolog", "swi-prolog", "dcg"),
        source_reference="dotfiles:.zara/experts/prolog",
        upstream_issue="lost-rob0t/prolog-rlm#495",
    ),
    LanguageExpertSpec(
        key="python",
        expert_id="zara:expert/python",
        namespace="python-expert",
        name="PythonExpert",
        language="python",
        extensions=(".py", ".pyi"),
        applicability_keywords=("python", "py", "pyi"),
        source_reference="dotfiles:.zara/experts/python",
        upstream_issue="lost-rob0t/prolog-rlm#498",
    ),
    LanguageExpertSpec(
        key="nim",
        expert_id="zara:expert/nim",
        namespace="nim-expert",
        name="NimExpert",
        language="nim",
        extensions=(".nim", ".nims", ".nimble"),
        applicability_keywords=("nim", "nims", "nimble"),
        source_reference="dotfiles:.zara/experts/nim",
        upstream_issue="lost-rob0t/prolog-rlm#499",
    ),
    LanguageExpertSpec(
        key="nix",
        expert_id="zara:expert/nix",
        namespace="nix-expert",
        name="NixExpert",
        language="nix",
        extensions=(".nix",),
        applicability_keywords=("nix", "nixos", "flake", "home-manager"),
        source_reference="dotfiles:.zara/experts/nix",
        upstream_issue="lost-rob0t/prolog-rlm#503",
    ),
    LanguageExpertSpec(
        key="bash",
        expert_id="zara:expert/bash",
        namespace="bash-expert",
        name="BashExpert",
        language="bash",
        extensions=(".sh", ".bash"),
        applicability_keywords=("bash", "shell", "sh"),
        source_reference="dotfiles:.zara/experts/bash",
        upstream_issue="lost-rob0t/prolog-rlm#502",
    ),
)

_SPEC_BY_ID: dict[str, LanguageExpertSpec] = {}
for _spec in _SPECS:
    _SPEC_BY_ID[_spec.key] = _spec
    _SPEC_BY_ID[_spec.expert_id] = _spec


def language_family_specs() -> tuple[LanguageExpertSpec, ...]:
    return _SPECS


def registered_predicates() -> dict[str, int]:
    return dict(_PREDICATES)


def matching_experts(path: str | Path) -> tuple[str, ...]:
    suffix = Path(path).suffix.lower()
    return tuple(spec.expert_id for spec in _SPECS if suffix in spec.extensions)


def _fields(*items: tuple[str, str, bool]) -> dict[str, list[dict[str, Any]]]:
    seen: set[str] = set()
    fields: list[dict[str, Any]] = []
    for name, field_type, required in items:
        if name in RESERVED_HOST_INPUT_FIELDS:
            raise ExpertError(f"operation input field {name!r} is reserved host metadata")
        if name in seen:
            raise ExpertError(f"duplicate operation input field: {name!r}")
        seen.add(name)
        fields.append({"name": name, "type": field_type, "required": required})
    return {"fields": fields}


def _operation_schema(operation: str) -> dict[str, Any]:
    # Every registered language predicate reserves its final Prolog argument for
    # a host-created result variable. Public ZARA-EXPERT/1 input fields therefore
    # describe exactly arity-1 caller values; callers can never inject a Prolog
    # variable descriptor or the Core-owned expert_operation selector.
    source_input = (
        ("source", "string", True),
        ("source_generation", "reference", True),
    )
    common_output = (
        ("evidence_refs", "list", False),
        ("explanation_refs", "list", False),
    )
    if operation == "match":
        return {
            "operation_id": operation,
            "input_schema": _fields(
                ("path", "string", True),
                ("source_generation", "reference", True),
            ),
            "output_schema": _fields(
                ("applicable", "boolean", True),
                *common_output,
            ),
        }
    if operation == "diagnose":
        return {
            "operation_id": operation,
            "input_schema": _fields(*source_input),
            "output_schema": _fields(
                ("diagnostics", "list", True),
                *common_output,
            ),
        }
    if operation == "repair.preview":
        return {
            "operation_id": operation,
            "input_schema": _fields(
                *source_input,
                ("diagnostic_ref", "reference", True),
            ),
            "output_schema": _fields(
                ("repair", "object", True),
                *common_output,
            ),
        }
    if operation == "repair.verify":
        return {
            "operation_id": operation,
            "input_schema": _fields(
                ("original_source", "string", True),
                ("candidate_source", "string", True),
                ("source_generation", "reference", True),
            ),
            "output_schema": _fields(
                ("verified", "boolean", True),
                ("postcondition_evidence", "object", True),
                *common_output,
            ),
        }
    if operation == "style.rules":
        return {
            "operation_id": operation,
            "input_schema": _fields(
                ("source", "string", True),
                ("project_style", "reference", True),
            ),
            "output_schema": _fields(
                ("style_rules", "list", True),
                ("style_provenance", "list", True),
                *common_output,
            ),
        }
    if operation == "explain":
        return {
            "operation_id": operation,
            "input_schema": _fields(
                ("decision_ref", "reference", True),
                ("source_generation", "reference", True),
            ),
            "output_schema": _fields(
                ("explanation", "object", True),
                *common_output,
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
    return {
        "operation_id": operation,
        "input_schema": _fields(*source_input),
        "output_schema": _fields(
            ("result", "object", True),
            *common_output,
        ),
    }


def language_expert_schemas() -> dict[str, dict[str, Any]]:
    """Expose closed operation schemas without creating a second protocol."""

    return {
        operation: {
            "input_schema": _operation_schema(operation)["input_schema"],
            "output_schema": _operation_schema(operation)["output_schema"],
        }
        for operation in (*_OPERATION_BINDINGS, "repair.apply")
    }


def _source_files(paths: Iterable[str | Path], expert_id: str) -> tuple[Path, ...]:
    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise ExpertError(
                f"configured {expert_id} expert source is not a regular file: {path}"
            )
        files.append(path)
    if not files:
        raise ExpertError(f"configured {expert_id} expert source list must not be empty")
    return tuple(files)


def register_language_family(
    host: ExpertHost,
    source_files_by_expert: Mapping[str, Iterable[str | Path]],
) -> frozenset[str]:
    """Bind configured Dotfiles-owned brains to existing host-issued authority.

    Source and authority validation is completed for the whole configured family
    before any namespace is mutated. A bad later source or conflicting later
    namespace therefore cannot leave a partially activated language family.
    """

    if not isinstance(source_files_by_expert, Mapping):
        raise ExpertError("language_expert_sources must be a mapping")
    unknown = set(source_files_by_expert) - {spec.key for spec in _SPECS}
    if unknown:
        raise ExpertError(f"unknown language expert source keys: {sorted(unknown)!r}")

    prepared: dict[str, tuple[Path, ...]] = {}
    for spec in _SPECS:
        configured = source_files_by_expert.get(spec.key)
        if configured is None:
            continue
        if isinstance(configured, (str, bytes, Path)):
            raise ExpertError(f"source list for {spec.key!r} must be a sequence of paths")
        prepared[spec.key] = _source_files(configured, spec.expert_id)

    for spec in _SPECS:
        files = prepared.get(spec.key)
        if files is not None:
            host.preflight_registration(spec.namespace, files, predicates=_PREDICATES)

    registered: set[str] = set()
    for spec in _SPECS:
        files = prepared.get(spec.key)
        if files is None:
            continue
        host.register(spec.namespace, files, predicates=_PREDICATES)
        registered.add(spec.key)
    return frozenset(registered)


def invoke_language_operation(
    host: ExpertHost,
    expert_id: str,
    operation: str,
    arguments: Sequence[Any] | None = None,
) -> dict[str, Any]:
    spec = _SPEC_BY_ID.get(expert_id)
    if spec is None:
        raise ExpertError(f"unknown language expert: {expert_id!r}")
    if operation == "repair.apply":
        raise ExpertError(
            "repair.apply requires Zara's canonical typed edit/effect path; "
            "expert registration grants no write authority"
        )
    binding = _OPERATION_BINDINGS.get(operation)
    if binding is None:
        raise ExpertError(f"unsupported language expert operation: {operation!r}")
    method = host.explain if binding.mode == "explain" else host.query
    result = method(spec.namespace, binding.predicate, arguments)
    evidence = result.get("results", [])
    explanation = result.get("trace", [])
    if not isinstance(evidence, list) or not isinstance(explanation, list):
        raise ExpertError(f"{spec.namespace}: malformed expert evidence")
    return {
        "protocol": PROTOCOL,
        "expert_id": spec.expert_id,
        "operation": operation,
        "source_reference": spec.source_reference,
        "evidence": evidence,
        "explanation": explanation,
        "model_calls": MAX_MODEL_CALLS,
        "effect_receipts": [],
    }


def _manifest_digest(spec: LanguageExpertSpec) -> str:
    bindings = ",".join(
        f"{operation}:{binding.predicate}/{binding.arity}:{binding.mode}"
        for operation, binding in sorted(_OPERATION_BINDINGS.items())
    )
    material = "|".join(
        (
            PROTOCOL,
            spec.expert_id,
            spec.source_reference,
            spec.upstream_issue,
            SOURCE_OWNER,
            bindings,
            "repair.apply:canonical-zara-effect-path",
            "style.rules:canonical-project-style-provenance",
            f"max_model_calls={MAX_MODEL_CALLS}",
        )
    )
    return f"sha256:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def descriptor(spec: LanguageExpertSpec, *, available: bool) -> dict[str, Any]:
    item: dict[str, Any] = {
        "protocol": PROTOCOL,
        "expert_id": spec.expert_id,
        "expert_version": "1",
        "package_namespace": "zara-expert",
        "manifest_digest": _manifest_digest(spec),
        "name": spec.name,
        "description": (
            f"Pure-symbolic {spec.name} adapter for deterministic {spec.language} "
            f"analysis, evidence, diagnostics and style rules; semantics "
            f"{spec.upstream_issue}, canonical brain {SOURCE_OWNER}."
        ),
        "source_reference": spec.source_reference,
        "reasoning_kind": "symbolic",
        "operations": [
            _operation_schema(name)
            for name in (*_OPERATION_BINDINGS.keys(), "repair.apply")
        ],
        "applicability": {"keywords": list(spec.applicability_keywords)},
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


def descriptors(registered: Iterable[str] = ()) -> tuple[dict[str, Any], ...]:
    available = frozenset(registered)
    # Keep the long-standing core language descriptors visible as absent while
    # optional packaged brains (currently Nix/Bash) enter the canonical registry
    # only when their exact source is configured and preflighted. This prevents
    # discovery from advertising a package whose pinned brain is not installed.
    return tuple(
        descriptor(spec, available=spec.key in available)
        for spec in _SPECS
        if spec.key in _BASE_DESCRIPTOR_KEYS or spec.key in available
    )


def register_descriptor_symbols(
    runtime: Any,
    registered: Iterable[str] = (),
) -> tuple[int, ...]:
    registrations: list[int] = []
    for item in descriptors(registered):
        registrations.append(
            runtime.register_symbol(
                item["expert_id"],
                SYMBOL_KIND,
                item,
                docs=item["description"],
                capabilities=(),
                source=item["source_reference"],
            )
        )
    return tuple(registrations)


__all__ = [
    "MAX_MODEL_CALLS",
    "PROTOCOL",
    "RESERVED_HOST_INPUT_FIELDS",
    "LanguageExpertSpec",
    "descriptor",
    "descriptors",
    "invoke_language_operation",
    "language_expert_schemas",
    "language_family_specs",
    "matching_experts",
    "register_descriptor_symbols",
    "register_language_family",
    "registered_predicates",
]
