from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from .domain import ExpertError, ExpertHost


PROTOCOL = "ZARA-EXPERT/1"
SYMBOL_KIND = "expert"
SOURCE_OWNER = "lost-rob0t/dotfiles#292"
MAX_MODEL_CALLS = 0


@dataclass(frozen=True)
class OperationBinding:
    predicate: str
    arity: int
    mode: str = "query"


@dataclass(frozen=True)
class LispExpertSpec:
    key: str
    expert_id: str
    namespace: str
    name: str
    dialect: str
    source_reference: str
    upstream_issue: str


_OPERATION_BINDINGS: Mapping[str, OperationBinding] = {
    "match": OperationBinding("can_handle", 2),
    "structural.check": OperationBinding("structural_check", 2),
    "structural.diagnose": OperationBinding("structural_diagnose", 2),
    "repair.preview": OperationBinding("preview_repair", 3),
    "repair.verify": OperationBinding("verify_repair", 3),
    "style.rules": OperationBinding("style_rules", 2),
    "explain": OperationBinding("explain_decision", 2, mode="explain"),
}

_PREDICATES: Mapping[str, int] = {
    binding.predicate: binding.arity for binding in _OPERATION_BINDINGS.values()
}

_SPECS: tuple[LispExpertSpec, ...] = (
    LispExpertSpec(
        key="lisp",
        expert_id="lisp",
        namespace="lisp",
        name="LispExpert",
        dialect="lisp",
        source_reference="dotfiles:.zara/experts/lisp",
        upstream_issue="lost-rob0t/prolog-rlm#494",
    ),
    LispExpertSpec(
        key="common-lisp",
        expert_id="common-lisp",
        namespace="common-lisp",
        name="CommonLispExpert",
        dialect="common-lisp",
        source_reference="dotfiles:.zara/experts/common-lisp",
        upstream_issue="lost-rob0t/prolog-rlm#496",
    ),
    LispExpertSpec(
        key="emacs-lisp",
        expert_id="emacs-lisp",
        namespace="emacs-lisp",
        name="EmacsLispExpert",
        dialect="emacs-lisp",
        source_reference="dotfiles:.zara/experts/emacs-lisp",
        upstream_issue="lost-rob0t/prolog-rlm#497",
    ),
)

_SPEC_BY_ID = {spec.expert_id: spec for spec in _SPECS}


def lisp_family_specs() -> tuple[LispExpertSpec, ...]:
    return _SPECS


def registered_predicates() -> dict[str, int]:
    return dict(_PREDICATES)


def _source_files(paths: Iterable[str | Path]) -> tuple[Path, ...]:
    files: list[Path] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise ExpertError(f"configured Lisp expert source is not a regular file: {path}")
        files.append(path)
    if not files:
        raise ExpertError("configured Lisp expert source list must not be empty")
    return tuple(files)


def register_lisp_family(
    host: ExpertHost,
    source_files_by_expert: Mapping[str, Iterable[str | Path]],
) -> frozenset[str]:
    """Register configured canonical brains through the existing expert host.

    This module intentionally contains no Lisp reader/parser implementation. The
    source files are the canonical Dotfiles-owned expert brains; this adapter
    owns only stable Zara namespace/operation bindings.
    """

    if not isinstance(source_files_by_expert, Mapping):
        raise ExpertError("lisp_family_sources must be a mapping")

    registered: set[str] = set()
    unknown = set(source_files_by_expert) - set(_SPEC_BY_ID)
    if unknown:
        raise ExpertError(f"unknown Lisp expert source keys: {sorted(unknown)!r}")

    for spec in _SPECS:
        configured = source_files_by_expert.get(spec.key)
        if configured is None:
            continue
        if isinstance(configured, (str, bytes, Path)):
            raise ExpertError(f"source list for {spec.key!r} must be a sequence of paths")
        files = _source_files(configured)
        host.register(spec.namespace, files, predicates=_PREDICATES)
        registered.add(spec.expert_id)
    return frozenset(registered)


def invoke_lisp_operation(
    host: ExpertHost,
    expert_id: str,
    operation: str,
    arguments: Sequence[Any] | None = None,
) -> dict[str, Any]:
    spec = _SPEC_BY_ID.get(expert_id)
    if spec is None:
        raise ExpertError(f"unknown Lisp expert: {expert_id!r}")
    if operation == "repair.apply":
        raise ExpertError(
            "repair.apply requires Zara's canonical typed edit/effect path; "
            "expert registration grants no write authority"
        )
    binding = _OPERATION_BINDINGS.get(operation)
    if binding is None:
        raise ExpertError(f"unsupported Lisp expert operation: {operation!r}")
    method = host.explain if binding.mode == "explain" else host.query
    return method(spec.namespace, binding.predicate, arguments)


def _operation_descriptor(name: str, binding: OperationBinding) -> dict[str, Any]:
    return {
        "name": name,
        "kind": "symbolic",
        "binding": {
            "authority": "registered-predicate",
            "predicate": binding.predicate,
            "arity": binding.arity,
        },
        "effects": [],
        "max_model_calls": 0,
    }


def descriptor(spec: LispExpertSpec, *, available: bool) -> dict[str, Any]:
    operations = [
        _operation_descriptor(name, binding)
        for name, binding in _OPERATION_BINDINGS.items()
    ]
    operations.append(
        {
            "name": "repair.apply",
            "kind": "effect",
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
            "max_model_calls": 0,
        }
    )
    return {
        "protocol": PROTOCOL,
        "expert_id": spec.expert_id,
        "version": "1",
        "package_namespace": "zara-expert",
        "name": spec.name,
        "description": f"Pure-symbolic {spec.name} adapter for {spec.dialect} structural and style reasoning.",
        "source_reference": spec.source_reference,
        "upstream_semantics": spec.upstream_issue,
        "canonical_source_owner": SOURCE_OWNER,
        "reasoning_kind": "symbolic",
        "dialect": spec.dialect,
        "operations": operations,
        "required_observations": ["source-bytes", "source-generation", "project-style-context"],
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
    "MAX_MODEL_CALLS",
    "PROTOCOL",
    "LispExpertSpec",
    "descriptor",
    "descriptors",
    "invoke_lisp_operation",
    "lisp_family_specs",
    "register_descriptor_symbols",
    "register_lisp_family",
    "registered_predicates",
]
