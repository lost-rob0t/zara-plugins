from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Mapping

from .domain import ExpertError
from .lisp_family import lisp_family_specs, registered_predicates


_POLICY_EXPORTS = {
    "provider_policy": 1,
    "max_model_calls": 1,
    "model_calls": 1,
}
_IDENTITY_EXPORTS = {
    "expert_id": 1,
    "upstream_contract": 1,
}
_POLICY_FACTS = {
    "provider_policy(disabled).": re.compile(r"\bprovider_policy\s*\(\s*disabled\s*\)\s*\."),
    "max_model_calls(0).": re.compile(r"\bmax_model_calls\s*\(\s*0\s*\)\s*\."),
    "model_calls(0).": re.compile(r"\bmodel_calls\s*\(\s*0\s*\)\s*\."),
}
_MODULE_EXPORTS_RE = re.compile(
    r":-\s*module\s*\(\s*[^,]+,\s*\[(.*?)\]\s*\)\s*\.",
    re.DOTALL,
)
_PREDICATE_INDICATOR_RE = re.compile(r"\b([a-z][A-Za-z0-9_]*)\s*/\s*([0-9]+)\b")
_BLOCK_COMMENT_RE = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT_RE = re.compile(r"%[^\n]*")


def _strip_comments(source: str) -> str:
    return _LINE_COMMENT_RE.sub("", _BLOCK_COMMENT_RE.sub("", source))


def _read_sources(paths: Iterable[str | Path], expert_id: str) -> tuple[str, ...]:
    rendered: list[str] = []
    for raw_path in paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise ExpertError(
                f"configured {expert_id} expert source is not a regular file: {path}"
            )
        try:
            rendered.append(path.read_text(encoding="utf-8"))
        except UnicodeError as exc:
            raise ExpertError(
                f"configured {expert_id} expert source is not UTF-8 text: {path}"
            ) from exc
    if not rendered:
        raise ExpertError(f"configured {expert_id} expert source list must not be empty")
    return tuple(rendered)


def _exported_predicates(sources: Iterable[str]) -> set[tuple[str, int]]:
    exports: set[tuple[str, int]] = set()
    for source in sources:
        stripped = _strip_comments(source)
        for module_exports in _MODULE_EXPORTS_RE.findall(stripped):
            exports.update(
                (name, int(arity))
                for name, arity in _PREDICATE_INDICATOR_RE.findall(module_exports)
            )
    return exports


def _fact_pattern(predicate: str, value: str) -> re.Pattern[str]:
    return re.compile(
        rf"\b{re.escape(predicate)}\s*\(\s*'{re.escape(value)}'\s*\)\s*\."
    )


def validate_lisp_source_contracts(
    source_files_by_expert: Mapping[str, Iterable[str | Path]],
) -> None:
    """Fail closed before Zara publishes a configured Lisp-family brain.

    Dotfiles owns the reader/dialect semantics. This adapter owns only the stable
    ZARA-EXPERT/1 ABI and therefore statically verifies the configured brain's
    exported predicates, canonical identity/upstream contract, and explicit
    provider-disabled/zero-model policy before any namespace is registered.
    """

    if not isinstance(source_files_by_expert, Mapping):
        raise ExpertError("lisp_family_sources must be a mapping")

    specs = {spec.key: spec for spec in lisp_family_specs()}
    unknown = set(source_files_by_expert) - set(specs)
    if unknown:
        raise ExpertError(f"unknown Lisp expert source keys: {sorted(unknown)!r}")

    required_exports = (
        set(registered_predicates().items())
        | set(_POLICY_EXPORTS.items())
        | set(_IDENTITY_EXPORTS.items())
    )
    for key, paths in source_files_by_expert.items():
        if isinstance(paths, (str, bytes, Path)):
            raise ExpertError(f"source list for {key!r} must be a sequence of paths")
        spec = specs[key]
        sources = _read_sources(paths, spec.expert_id)
        exports = _exported_predicates(sources)
        missing = sorted(required_exports - exports)
        if missing:
            rendered = ", ".join(f"{name}/{arity}" for name, arity in missing)
            raise ExpertError(
                f"configured {spec.expert_id} brain is not adapter-ready; "
                f"missing exported predicates: {rendered}"
            )

        combined = "\n".join(_strip_comments(source) for source in sources)
        missing_policy = [
            fact for fact, pattern in _POLICY_FACTS.items() if not pattern.search(combined)
        ]
        if missing_policy:
            raise ExpertError(
                f"configured {spec.expert_id} brain does not pin pure-symbolic policy: "
                + ", ".join(missing_policy)
            )

        identity_expectations = {
            "expert_id": spec.expert_id,
            "upstream_contract": spec.upstream_issue,
        }
        missing_identity = [
            f"{predicate}('{value}')."
            for predicate, value in identity_expectations.items()
            if not _fact_pattern(predicate, value).search(combined)
        ]
        if missing_identity:
            raise ExpertError(
                f"configured {spec.expert_id} brain identity does not match adapter contract: "
                + ", ".join(missing_identity)
            )


__all__ = ["validate_lisp_source_contracts"]
