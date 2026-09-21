from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
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
_VERIFIED_OUTCOME_REF_RE = re.compile(
    r"^zara\.verified-outcome/v1:(?:effect|outcome):"
    r"[A-Za-z0-9][A-Za-z0-9._:/#-]{0,383}$"
)
_VERIFIED_POSTCONDITION_PREFIX = "zara.verified-outcome/v1:outcome:postcondition/"
_REQUIRED_POSTCONDITION_RE = re.compile(
    r"required_postcondition\(([a-z][a-z0-9_]*)\)"
)
_REQUIRED_POSTCONDITIONS = {
    "zara:expert/common-lisp": "sbcl_fresh_reader_and_compile_evidence",
    "zara:expert/emacs-lisp": "emacs_fresh_reader_and_byte_compile_evidence",
}
VerifiedOutcomeResolver = Callable[..., Mapping[str, Any] | None]


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
    """Register canonical Dotfiles brains without implementing a second reader."""

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


def _content_addressed_evidence_ref(item: Any) -> str:
    encoded = str(item).encode("utf-8", errors="strict")
    digest = hashlib.sha256(encoded).hexdigest()
    return f"evidence:lisp:sha256:{digest}"


def _core_evidence_refs(result: Mapping[str, Any]) -> list[str]:
    """Project bounded proof lineage without exposing raw result text as a ref."""

    raw_trace = result.get("trace", ())
    if isinstance(raw_trace, (str, bytes)) or not isinstance(raw_trace, (list, tuple)):
        raise ExpertError("Lisp expert trace must be a sequence")
    if len(raw_trace) > _MAX_CORE_EVIDENCE_REFS:
        raise ExpertError(f"Lisp expert trace exceeds {_MAX_CORE_EVIDENCE_REFS} entries")
    if raw_trace:
        return [_content_addressed_evidence_ref(item) for item in raw_trace]

    raw_results = result.get("results", ())
    if isinstance(raw_results, (str, bytes)) or not isinstance(raw_results, (list, tuple)):
        raise ExpertError("Lisp expert results must be a sequence")
    if len(raw_results) > _MAX_CORE_EVIDENCE_REFS:
        raise ExpertError(f"Lisp expert evidence exceeds {_MAX_CORE_EVIDENCE_REFS} entries")

    return [_content_addressed_evidence_ref(item) for item in raw_results]


def _pending_postcondition(
    spec: LispExpertSpec,
    result: Mapping[str, Any],
) -> str | None:
    """Return the one dialect postcondition explicitly requested by the brain."""

    expected = _REQUIRED_POSTCONDITIONS.get(spec.expert_id)
    if expected is None:
        return None
    raw_results = result.get("results", ())
    if isinstance(raw_results, (str, bytes)) or not isinstance(raw_results, (list, tuple)):
        return None
    rendered = tuple(str(item) for item in raw_results)
    if not any("verified(false)" in item for item in rendered):
        return None
    required: set[str] = set()
    for item in rendered:
        required.update(_REQUIRED_POSTCONDITION_RE.findall(item))
    if required != {expected}:
        return None
    return expected


def _verified_postcondition_ref(
    receipt: Any,
    *,
    expert_id: str,
    source_generation: str,
    candidate_sha256: str,
    required_postcondition: str,
) -> str | None:
    """Validate one trusted Core verified-outcome receipt without running tools."""

    if not isinstance(receipt, Mapping):
        return None
    receipt_ref = receipt.get("receipt_ref")
    if not isinstance(receipt_ref, str):
        return None
    if not receipt_ref.startswith(_VERIFIED_POSTCONDITION_PREFIX):
        return None
    if _VERIFIED_OUTCOME_REF_RE.fullmatch(receipt_ref) is None:
        return None
    if receipt.get("expert_id") != expert_id:
        return None
    if receipt.get("source_generation") != source_generation:
        return None
    if receipt.get("candidate_sha256") != candidate_sha256:
        return None
    if receipt.get("required_postcondition") != required_postcondition:
        return None
    if type(receipt.get("verified")) is not bool or receipt["verified"] is not True:
        return None
    if type(receipt.get("fresh")) is not bool or receipt["fresh"] is not True:
        return None
    return receipt_ref


def make_lisp_expert_handler(
    host: ExpertHost,
    expert_id: str,
    *,
    verified_outcome_resolver: VerifiedOutcomeResolver | None = None,
):
    """Return one Core-compatible ZARA-EXPERT/1 Lisp-family handler.

    The resolver is a trusted read-only host seam for a receipt already produced
    by Zara's canonical effect/postcondition authority. It never executes SBCL,
    Emacs, tools, effects, providers, or network calls. Dialect verification
    remains blocked unless the symbolic brain explicitly requests its canonical
    postcondition and the receipt is exact, fresh, generation-bound, and bound
    to the candidate source digest.
    """

    spec = _SPEC_BY_ID.get(expert_id)
    if spec is None:
        raise ExpertError(f"unknown Lisp expert: {expert_id!r}")
    if verified_outcome_resolver is not None and not callable(verified_outcome_resolver):
        raise TypeError("verified_outcome_resolver must be callable")

    def handler(
        *,
        expert_operation: str,
        arguments: list[Any] | None = None,
        repair: dict[str, Any] | None = None,
        expected_preimage: str | None = None,
        source_generation: str | None = None,
    ) -> dict[str, Any]:
        if expert_operation == "repair.apply":
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

        if repair is not None or expected_preimage is not None:
            raise ExpertError(
                "repair effect fields are accepted only for repair.apply through Zara Core"
            )
        if source_generation is not None and expert_operation != "repair.verify":
            raise ExpertError("source_generation is accepted only for repair.verify or repair.apply")

        private_arguments = _core_operation_arguments(expert_operation, arguments)
        public_arguments = [] if arguments is None else list(arguments)
        result = invoke_lisp_operation(
            host,
            spec.expert_id,
            expert_operation,
            private_arguments,
        )
        evidence_refs = _core_evidence_refs(result)
        ok = result.get("ok")
        if ok is True:
            verdict = "blocked" if expert_operation == "repair.verify" else "succeeded"
        elif ok is False:
            verdict = "failed"
        else:
            verdict = "unknown"

        data: dict[str, Any] = {"result": result}
        if expert_operation == "repair.verify" and verdict == "blocked":
            required_postcondition = _pending_postcondition(spec, result)
            candidate_source = public_arguments[1] if len(public_arguments) == 2 else None
            if (
                required_postcondition is not None
                and verified_outcome_resolver is not None
                and isinstance(candidate_source, str)
                and isinstance(source_generation, str)
                and len(evidence_refs) < _MAX_CORE_EVIDENCE_REFS
            ):
                candidate_sha256 = hashlib.sha256(
                    candidate_source.encode("utf-8", errors="strict")
                ).hexdigest()
                try:
                    receipt = verified_outcome_resolver(
                        expert_id=spec.expert_id,
                        source_generation=source_generation,
                        candidate_sha256=candidate_sha256,
                        required_postcondition=required_postcondition,
                    )
                except Exception:
                    receipt = None
                receipt_ref = _verified_postcondition_ref(
                    receipt,
                    expert_id=spec.expert_id,
                    source_generation=source_generation,
                    candidate_sha256=candidate_sha256,
                    required_postcondition=required_postcondition,
                )
                if receipt_ref is not None:
                    verdict = "succeeded"
                    evidence_refs.append(receipt_ref)
                    data.update(
                        {
                            "verified": True,
                            "verified_outcome_ref": receipt_ref,
                            "postcondition_evidence": {
                                "receipt_ref": receipt_ref,
                                "required_postcondition": required_postcondition,
                                "source_generation": source_generation,
                                "candidate_sha256": candidate_sha256,
                            },
                        }
                    )

        return {
            "verdict": verdict,
            "data": data,
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
    if name == "repair.verify":
        return {
            "operation_id": name,
            "input_schema": _fields(
                ("arguments", "list", False),
                ("source_generation", "reference", False),
            ),
            "output_schema": _fields(
                ("result", "object", True),
                ("evidence_refs", "list", False),
                ("postcondition_evidence", "object", False),
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
            "repair.verify:canonical-verified-outcome-read-seam",
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
    "VerifiedOutcomeResolver",
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
