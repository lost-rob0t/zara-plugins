from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .domain import ExpertError, ExpertHost


PROTOCOL = "ZARA-EXPERT/1"
SYMBOL_KIND = "expert"
SOURCE_OWNER = "lost-rob0t/dotfiles#292"
MAX_MODEL_CALLS = 0
APPLICABILITY_SCHEMA = "schema:zara.language-expert.applicability.v1"
RESULT_SCHEMA = "schema:zara.language-expert.result.v1"


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
        expert_id="prolog",
        namespace="prolog-expert",
        name="PrologExpert",
        language="prolog",
        extensions=(".pl", ".pro", ".prolog"),
        source_reference="dotfiles:.zara/experts/prolog",
        upstream_issue="lost-rob0t/prolog-rlm#495",
    ),
    LanguageExpertSpec(
        key="python",
        expert_id="python",
        namespace="python-expert",
        name="PythonExpert",
        language="python",
        extensions=(".py", ".pyi"),
        source_reference="dotfiles:.zara/experts/python",
        upstream_issue="lost-rob0t/prolog-rlm#498",
    ),
    LanguageExpertSpec(
        key="nim",
        expert_id="nim",
        namespace="nim-expert",
        name="NimExpert",
        language="nim",
        extensions=(".nim", ".nims", ".nimble"),
        source_reference="dotfiles:.zara/experts/nim",
        upstream_issue="lost-rob0t/prolog-rlm#499",
    ),
)

_SPEC_BY_ID = {spec.expert_id: spec for spec in _SPECS}


def language_family_specs() -> tuple[LanguageExpertSpec, ...]:
    return _SPECS


def registered_predicates() -> dict[str, int]:
    return dict(_PREDICATES)


def matching_experts(path: str | Path) -> tuple[str, ...]:
    suffix = Path(path).suffix.lower()
    return tuple(spec.expert_id for spec in _SPECS if suffix in spec.extensions)


def language_expert_schemas() -> dict[str, dict[str, Any]]:
    """Return inert domain schemas; ZARA-EXPERT/1 itself remains Zara-owned."""

    return {
        APPLICABILITY_SCHEMA: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": ["path", "source_generation", "project_style"],
            "properties": {
                "path": {"type": "string", "minLength": 1, "maxLength": 4096},
                "source_generation": {"type": "string", "minLength": 1, "maxLength": 128},
                "project_style": {"type": "string", "minLength": 1, "maxLength": 128},
            },
        },
        RESULT_SCHEMA: {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "additionalProperties": False,
            "required": [
                "protocol",
                "expert_id",
                "operation",
                "source_reference",
                "evidence",
                "explanation",
                "model_calls",
            ],
            "properties": {
                "protocol": {"const": PROTOCOL},
                "expert_id": {"enum": [spec.expert_id for spec in _SPECS]},
                "operation": {
                    "enum": [*list(_OPERATION_BINDINGS), "repair.apply"],
                },
                "source_reference": {"type": "string"},
                "evidence": {"type": "array"},
                "explanation": {"type": "array"},
                "model_calls": {"const": 0},
            },
        },
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
    """Bind configured Dotfiles-owned brains to the existing host authority."""

    if not isinstance(source_files_by_expert, Mapping):
        raise ExpertError("language_expert_sources must be a mapping")
    unknown = set(source_files_by_expert) - set(_SPEC_BY_ID)
    if unknown:
        raise ExpertError(f"unknown language expert source keys: {sorted(unknown)!r}")

    registered: set[str] = set()
    for spec in _SPECS:
        configured = source_files_by_expert.get(spec.key)
        if configured is None:
            continue
        if isinstance(configured, (str, bytes, Path)):
            raise ExpertError(f"source list for {spec.key!r} must be a sequence of paths")
        files = _source_files(configured, spec.expert_id)
        host.register(spec.namespace, files, predicates=_PREDICATES)
        registered.add(spec.expert_id)
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
    }


def _operation_descriptor(name: str, binding: OperationBinding) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "symbolic",
        "input_schema": APPLICABILITY_SCHEMA,
        "output_schema": RESULT_SCHEMA,
        "binding": {
            "authority": "registered-predicate",
            "predicate": binding.predicate,
            "arity": binding.arity,
        },
        "effects": [],
        "max_model_calls": MAX_MODEL_CALLS,
    }


def descriptor(spec: LanguageExpertSpec, *, available: bool) -> dict[str, Any]:
    operations = [
        _operation_descriptor(name, binding)
        for name, binding in _OPERATION_BINDINGS.items()
    ]
    operations.append(
        {
            "name": "repair.apply",
            "kind": "effect",
            "input_schema": APPLICABILITY_SCHEMA,
            "output_schema": RESULT_SCHEMA,
            "binding": None,
            "effects": [
                {
                    "type": "typed-edit",
                    "authority": "canonical-zara-effect-path",
                    "requires_expected_preimage": True,
                    "requires_fresh_postcondition": True,
                }
            ],
            "availability": "requires-canonical-edit-capability",
            "max_model_calls": MAX_MODEL_CALLS,
        }
    )
    return {
        "protocol": PROTOCOL,
        "expert_id": spec.expert_id,
        "version": "1",
        "package_namespace": "zara-expert",
        "name": spec.name,
        "description": (
            f"Pure-symbolic {spec.name} adapter for deterministic {spec.language} "
            "analysis, evidence, diagnostics and style rules."
        ),
        "source_reference": spec.source_reference,
        "upstream_semantics": spec.upstream_issue,
        "canonical_source_owner": SOURCE_OWNER,
        "reasoning_kind": "symbolic",
        "language": spec.language,
        "extensions": list(spec.extensions),
        "applicability_schema": APPLICABILITY_SCHEMA,
        "result_schema": RESULT_SCHEMA,
        "operations": operations,
        "required_observations": [
            "source-bytes",
            "source-generation",
            "project-style-context",
        ],
        "required_capabilities": [],
        "fallback": {"provider": False, "model": False, "remote": False},
        "delegation": {"shared_budget_required": True, "authority_may_only_narrow": True},
        "resource_limits": {"max_model_calls": MAX_MODEL_CALLS},
        "availability": "available" if available else "source-unavailable",
    }


def descriptors(registered: Iterable[str] = ()) -> tuple[dict[str, Any], ...]:
    available = frozenset(registered)
    return tuple(descriptor(spec, available=spec.expert_id in available) for spec in _SPECS)


def register_descriptor_symbols(runtime: Any, registered: Iterable[str] = ()) -> tuple[int, ...]:
    registrations: list[int] = []
    for item in descriptors(registered):
        registrations.append(
            runtime.register_symbol(
                f"zara:expert/{item['expert_id']}",
                SYMBOL_KIND,
                item,
                docs=item["description"],
                capabilities=(),
                source=item["source_reference"],
            )
        )
    return tuple(registrations)


__all__ = [
    "APPLICABILITY_SCHEMA",
    "MAX_MODEL_CALLS",
    "PROTOCOL",
    "RESULT_SCHEMA",
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
