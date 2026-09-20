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
_RESULT_VARIABLE = {"var": "Result"}
_MAX_CORE_EVIDENCE_REFS = 32


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
        expert_id="zara:expert/lisp",
        namespace="lisp",
        name="LispExpert",
        dialect="lisp",
        source_reference="dotfiles:.zara/experts/lisp",
        upstream_issue="lost-rob0t/prolog-rlm#494",
    ),
    LispExpertSpec(
        key="common-lisp",
        expert_id="zara:expert/common-lisp",
        namespace="common-lisp",
        name="CommonLispExpert",
        dialect="common-lisp",
        source_reference="dotfiles:.zara/experts/common-lisp",
        upstream_issue="lost-rob0t/prolog-rlm#496",
    ),
    LispExpertSpec(
        key="emacs-lisp",
        expert_id="zara:expert/emacs-lisp",
        namespace="emacs-lisp",
        name="EmacsLispExpert",
        dialect="emacs-lisp",
        source_reference="dotfiles:.zara/experts/emacs-lisp",
        upstream_issue="lost-rob0t/prolog-rlm#497",
    ),
)

_SPEC_BY_ID: dict[str, LispExpertSpec] = {}
for _spec in _SPECS:
    _SPEC_BY_ID[_spec.key] = _spec
    _SPEC_BY_ID[_spec.expert_id] = _spec


_APP_KEYWORDS: Mapping[str, tuple[str, ...]] = {
    "lisp": ("lisp",),
    "common-lisp": ("common-lisp", "commonlisp", "lisp"),
    "emacs-lisp": ("emacs-lisp", "elisp", "lisp"),
}


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

    Source and authority validation is completed for the whole configured family
    before any host namespace is mutated. A bad later source or conflicting later
    namespace therefore cannot leave a partially registered Lisp family behind.
    """

    if not isinstance(source_files_by_expert, Mapping):
        raise ExpertError("lisp_family_sources must be a mapping")

    unknown = set(source_files_by_expert) - {spec.key for spec in _SPECS}
    if unknown:
        raise ExpertError(f"unknown Lisp expert source keys: {sorted(unknown)!r}")

    validated_sources: dict[str, tuple[Path, ...]] = {}
    for spec in _SPECS:
        configured = source_files_by_expert.get(spec.key)
        if configured is None:
            continue
        if isinstance(configured, (str, bytes, Path)):
            raise ExpertError(f"source list for {spec.key!r} must be a sequence of paths")
        validated_sources[spec.key] = _source_files(configured)

    for spec in _SPECS:
        files = validated_sources.get(spec.key)
        if files is not None:
            host.preflight_registration(spec.namespace, files, predicates=_PREDICATES)

    registered: set[str] = set()
    for spec in _SPECS:
        files = validated_sources.get(spec.key)
        if files is None:
            continue
        host.register(spec.namespace, files, predicates=_PREDICATES)
        registered.add(spec.key)
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
    if operation == "repair.preview" and spec.key != "lisp":
        raise ExpertError(
            f"repair.preview for {spec.expert_id} requires canonical ZARA-EXPERT/1 "
            "delegation to zara:expert/lisp with the caller's remaining shared budget; "
            "direct dialect-host dispatch is forbidden"
        )
    binding = _OPERATION_BINDINGS.get(operation)
    if binding is None:
        raise ExpertError(f"unsupported Lisp expert operation: {operation!r}")
    method = host.explain if binding.mode == "explain" else host.query
    return method(spec.namespace, binding.predicate, arguments)


def _core_operation_arguments(
    expert_operation: str,
    arguments: list[Any] | None,
) -> list[Any]:
    binding = _OPERATION_BINDINGS.get(expert_operation)
    if binding is None:
        raise ExpertError(f"unsupported Lisp expert operation: {expert_operation!r}")

    if arguments is None:
        public_arguments: list[Any] = []
    elif isinstance(arguments, list):
        public_arguments = list(arguments)
    else:
        raise ExpertError("Lisp expert arguments must be a list of ground values")

    expected_count = binding.arity - 1
    if len(public_arguments) != expected_count:
        raise ExpertError(
            f"Lisp expert operation {expert_operation!r} requires "
            f"{expected_count} public ground argument(s)"
        )

    for argument in public_arguments:
        if isinstance(argument, Mapping) and set(argument) == {"var"}:
            raise ExpertError(
                "caller-supplied Prolog result variable is forbidden; "
                "Lisp expert arguments must be ground"
            )

    return [*public_arguments, dict(_RESULT_VARIABLE)]


def _core_evidence_refs(result: Mapping[str, Any]) -> list[str]:
    """Project bounded proof lineage without exposing raw result text as a ref."""

    raw_trace = result.get("trace", ())
    if isinstance(raw_trace, (str, bytes)) or not isinstance(raw_trace, (list, tuple)):
        raise ExpertError("Lisp expert trace must be a sequence")
    if len(raw_trace) > _MAX_CORE_EVIDENCE_REFS:
        raise ExpertError(
            f"Lisp expert trace exceeds {_MAX_CORE_EVIDENCE_REFS} entries"
        )
    if raw_trace:
        return [str(item) for item in raw_trace]

    raw_results = result.get("results", ())
    if isinstance(raw_results, (str, bytes)) or not isinstance(raw_results, (list, tuple)):
        raise ExpertError("Lisp expert results must be a sequence")
    if len(raw_results) > _MAX_CORE_EVIDENCE_REFS:
        raise ExpertError(
            f"Lisp expert evidence exceeds {_MAX_CORE_EVIDENCE_REFS} entries"
        )

    refs: list[str] = []
    for item in raw_results:
        encoded = str(item).encode("utf-8", errors="strict")
        digest = hashlib.sha256(encoded).hexdigest()
        refs.append(f"evidence:lisp:sha256:{digest}")
    return refs


def make_lisp_expert_handler(host: ExpertHost, expert_id: str):
    """Return one handler compatible with Zara Core's ZARA-EXPERT/1 registry.

    ``expert_operation`` is host-owned metadata injected by the canonical Core
    registry. It is deliberately not part of any public operation input schema.
    The adapter reports an explicit zero model-call ledger on every returned
    outcome and never applies filesystem edits itself.
    """

    spec = _SPEC_BY_ID.get(expert_id)
    if spec is None:
        raise ExpertError(f"unknown Lisp expert: {expert_id!r}")

    def handler(
        *,
        expert_operation: str,
        arguments: list[Any] | None = None,
        repair: dict[str, Any] | None = None,
        expected_preimage: str | None = None,
        source_generation: str | None = None,
    ) -> dict[str, Any]:
        if expert_operation == "repair.apply":
            # The descriptor advertises that this expert can participate in a
            # repair workflow, but write authority belongs to Zara Core's typed
            # effect path. Returning BLOCKED is intentional: the caller must
            # cross approval/capability fencing and then provide fresh
            # postcondition evidence rather than letting this plugin write.
            return {
                "verdict": "blocked",
                "data": {
                    "reason": "canonical-typed-edit-required",
                    "expert_id": spec.expert_id,
                },
                "evidence_refs": [],
                "usage": {"model_calls": MAX_MODEL_CALLS},
                "effect_receipts": [],
            }

        if repair is not None or expected_preimage is not None or source_generation is not None:
            raise ExpertError(
                "repair effect fields are accepted only for repair.apply through Zara Core"
            )

        private_arguments = _core_operation_arguments(expert_operation, arguments)
        result = invoke_lisp_operation(
            host,
            spec.expert_id,
            expert_operation,
            private_arguments,
        )
        evidence_refs = _core_evidence_refs(result)
        ok = result.get("ok")
        if ok is True:
            # A successful registered-predicate query proves only that the
            # symbolic verifier ran. The canonical Lisp-family brains
            # intentionally require a fresh dialect reader/compiler
            # postcondition before a repair may be called verified, so Core must
            # not receive a succeeded domain verdict from this predicate alone.
            verdict = "unknown" if expert_operation == "repair.verify" else "succeeded"
        elif ok is False:
            verdict = "failed"
        else:
            verdict = "unknown"
        return {
            "verdict": verdict,
            "data": {"result": result},
            "evidence_refs": evidence_refs,
            "usage": {"model_calls": MAX_MODEL_CALLS},
            "effect_receipts": [],
        }

    return handler


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


def _operation_descriptor(name: str) -> dict[str, Any]:
    if name == "repair.apply":
        return {
            "operation_id": name,
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
        "operation_id": name,
        "input_schema": _fields(("arguments", "list", False)),
        "output_schema": _fields(
            ("result", "object", True),
            ("evidence_refs", "list", False),
        ),
    }


def _manifest_digest(spec: LispExpertSpec) -> str:
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
            "dialect-repair-preview:delegate-to-zara:expert/lisp",
            "repair.verify:fresh-dialect-postcondition-required",
            "repair.apply:canonical-zara-effect-path",
            f"max_model_calls={MAX_MODEL_CALLS}",
        )
    )
    return f"sha256:{hashlib.sha256(material.encode('utf-8')).hexdigest()}"


def descriptor(spec: LispExpertSpec, *, available: bool) -> dict[str, Any]:
    operations = [
        _operation_descriptor(name)
        for name in (*_OPERATION_BINDINGS.keys(), "repair.apply")
    ]
    item: dict[str, Any] = {
        "protocol": PROTOCOL,
        "expert_id": spec.expert_id,
        "expert_version": "1",
        "package_namespace": "zara-expert",
        "manifest_digest": _manifest_digest(spec),
        "name": spec.name,
        "description": (
            f"Pure-symbolic {spec.name} adapter for {spec.dialect} structural and style reasoning; "
            f"semantics {spec.upstream_issue}, canonical brain {SOURCE_OWNER}."
        ),
        "source_reference": spec.source_reference,
        "reasoning_kind": "symbolic",
        "operations": operations,
        "applicability": {"keywords": list(_APP_KEYWORDS[spec.key])},
        "required_capabilities": [],
        "possible_effects": ["filesystem_write"],
        "supported_engines": ["swipl"],
        "supported_platforms": [],
        "fallback_policy": "fail_closed",
        "delegation_policy": "never" if spec.key == "lisp" else "children",
        "resource_limits": {"max_model_calls": MAX_MODEL_CALLS},
        "registry_generation": 0,
        "availability": "available" if available else "absent",
    }
    if not available:
        item["unavailable_reason"] = "source-unavailable"
    return item


def descriptors(registered: Iterable[str] = ()) -> tuple[dict[str, Any], ...]:
    available = frozenset(registered)
    return tuple(descriptor(spec, available=spec.key in available) for spec in _SPECS)


def register_descriptor_symbols(runtime: Any, registered: Iterable[str] = ()) -> tuple[int, ...]:
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
    "LispExpertSpec",
    "descriptor",
    "descriptors",
    "invoke_lisp_operation",
    "lisp_family_specs",
    "make_lisp_expert_handler",
    "register_descriptor_symbols",
    "register_lisp_family",
    "registered_predicates",
]
