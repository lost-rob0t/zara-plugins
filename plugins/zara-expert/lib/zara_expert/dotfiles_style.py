from __future__ import annotations

from dataclasses import dataclass
import re

from .composition import InvocationFence
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
    workspace_id: str
    workspace_generation: int

    def reference_for(self, fence: InvocationFence) -> str:
        """Return an inert style reference only for the generation that resolved it."""

        fence.check()
        if (
            fence.workspace_id != self.workspace_id
            or fence.workspace_generation != self.workspace_generation
        ):
            raise ExpertError("DotfilesExpert stale workspace generation for style source")
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


def _query_one(
    host: ExpertHost,
    *,
    predicate: str,
    arguments: list,
    fence: InvocationFence,
) -> str:
    """Fence every registered-predicate read before and after host dispatch."""

    fence.check()
    result = host.query(NAMESPACE, predicate, arguments)
    fence.check()
    return _single_result(result, predicate=predicate)


def _style_source(
    host: ExpertHost,
    *,
    scope: str,
    language: str,
    fence: InvocationFence,
) -> DotfilesStyleSource:
    raw = _query_one(
        host,
        predicate="style_source",
        arguments=[scope, language, {"var": "Path"}, {"var": "Revision"}],
        fence=fence,
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
    revision_raw = _query_one(
        host,
        predicate="style_revision",
        arguments=[revision_key, {"var": "Revision"}],
        fence=fence,
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
        workspace_id=fence.workspace_id,
        workspace_generation=fence.workspace_generation,
    )


def style_sources_for_language(
    host: ExpertHost,
    language: str,
    *,
    fence: InvocationFence,
) -> tuple[DotfilesStyleSource, DotfilesStyleSource]:
    """Resolve trusted project + language style refs through registered predicates.

    Resolution is bound to the caller-owned workspace generation. Every host read
    is fenced before and after dispatch, so cancellation or a project switch can
    never publish a late style reference. Returned references are inert and must
    be revalidated against the same fence before use; no style file is read,
    consulted, executed, or granted authority here.
    """

    if language not in _SUPPORTED_LANGUAGES:
        raise ExpertError(f"unsupported DotfilesExpert style language: {language!r}")
    fence.check()
    project = _style_source(host, scope="project", language="any", fence=fence)
    language_source = _style_source(
        host,
        scope="project_language",
        language=language,
        fence=fence,
    )
    fence.check()
    return project, language_source


__all__ = ["DotfilesStyleSource", "style_sources_for_language"]
