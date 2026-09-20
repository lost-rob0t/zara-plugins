from __future__ import annotations

from dataclasses import dataclass
import re

from .domain import ExpertError, ExpertHost
from .dotfiles_family import NAMESPACE


_SUPPORTED_LANGUAGES = frozenset({"nix", "bash"})
_STYLE_SOURCE_RE = re.compile(
    r"^style_source\((project|project_language),(any|nix|bash),'([^'\\]{1,256})','([a-z0-9][a-z0-9._-]{0,127})'\)$"
)
_STYLE_REVISION_RE = re.compile(
    r"^style_revision\((project|nix|bash),'([a-z0-9][a-z0-9._-]{0,127})'\)$"
)


@dataclass(frozen=True)
class DotfilesStyleSource:
    scope: str
    language: str
    source_reference: str
    revision: str

    @property
    def reference(self) -> str:
        return f"style:{self.revision}:{self.source_reference}"


def _single_result(result: dict, *, predicate: str) -> str:
    if result.get("ok") is not True:
        raise ExpertError(f"DotfilesExpert predicate {predicate!r} failed")
    raw = result.get("results")
    if isinstance(raw, (str, bytes)) or not isinstance(raw, list) or len(raw) != 1:
        raise ExpertError(
            f"DotfilesExpert predicate {predicate!r} must return exactly one result"
        )
    value = raw[0]
    if not isinstance(value, str):
        raise ExpertError(f"DotfilesExpert predicate {predicate!r} returned non-text")
    return value


def _style_source(host: ExpertHost, *, scope: str, language: str) -> DotfilesStyleSource:
    raw = _single_result(
        host.query(
            NAMESPACE,
            "style_source",
            [scope, language, {"var": "Path"}, {"var": "Revision"}],
        ),
        predicate="style_source",
    )
    match = _STYLE_SOURCE_RE.fullmatch(raw)
    if match is None:
        raise ExpertError("DotfilesExpert style_source returned malformed evidence")
    actual_scope, actual_language, source_reference, revision = match.groups()
    if actual_scope != scope or actual_language != language:
        raise ExpertError("DotfilesExpert style_source returned mismatched scope")

    expected_source = (
        ".zara/style/project.pl"
        if scope == "project"
        else f".zara/style/languages/{language}.pl"
    )
    if source_reference != expected_source:
        raise ExpertError("DotfilesExpert style_source escaped the canonical .zara/style root")

    revision_key = "project" if scope == "project" else language
    revision_raw = _single_result(
        host.query(
            NAMESPACE,
            "style_revision",
            [revision_key, {"var": "Revision"}],
        ),
        predicate="style_revision",
    )
    revision_match = _STYLE_REVISION_RE.fullmatch(revision_raw)
    if revision_match is None:
        raise ExpertError("DotfilesExpert style_revision returned malformed evidence")
    actual_key, canonical_revision = revision_match.groups()
    if actual_key != revision_key or canonical_revision != revision:
        raise ExpertError("DotfilesExpert style source revision mismatch")

    return DotfilesStyleSource(
        scope=scope,
        language=language,
        source_reference=source_reference,
        revision=revision,
    )


def style_sources_for_language(
    host: ExpertHost,
    language: str,
) -> tuple[DotfilesStyleSource, DotfilesStyleSource]:
    """Resolve trusted project + language style refs through registered predicates.

    This returns inert source references only. It does not read, consult, execute,
    or grant authority from the style files, and it has no provider/model fallback.
    """

    if language not in _SUPPORTED_LANGUAGES:
        raise ExpertError(f"unsupported DotfilesExpert style language: {language!r}")
    project = _style_source(host, scope="project", language="any")
    language_source = _style_source(
        host,
        scope="project_language",
        language=language,
    )
    return project, language_source


__all__ = ["DotfilesStyleSource", "style_sources_for_language"]
