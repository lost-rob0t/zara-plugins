"""Wiki gate registry, MediaWiki adapter, and bounded federation."""

from __future__ import annotations

import html
import ipaddress
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable, Iterable, Mapping

from .core import SourcedResult
from .store import WikiStore


_GATE_ID = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_LANGUAGE = re.compile(r"^[A-Za-z0-9-]{1,32}$")
_TAGS = re.compile(r"<[^>]+>")


class WikiGateError(RuntimeError):
    def __init__(self, message: str, *, kind: str = "unavailable") -> None:
        super().__init__(message)
        self.kind = kind


@dataclass(frozen=True)
class GateSpec:
    gate_id: str
    name: str
    engine: str
    base_url: str
    api_url: str = ""
    language: str = ""
    builtin: bool = False
    template: bool = False

    @classmethod
    def custom(
        cls,
        gate_id: str,
        base_url: str,
        *,
        engine: str,
        name: str = "",
        api_url: str = "",
        language: str = "",
        builtin: bool = False,
        template: bool = False,
    ) -> "GateSpec":
        normalized_id = _validate_gate_id(gate_id)
        normalized_engine = str(engine).strip().lower()
        if normalized_engine not in GateCatalog.ENGINES:
            raise WikiGateError(f"unsupported wiki engine {engine!r}", kind="invalid_gate")
        normalized_base = _validate_base_url(base_url)
        normalized_api = ""
        if api_url:
            normalized_api = _validate_api_url(api_url, normalized_base)
        elif normalized_engine in {"mediawiki", "wikidata"}:
            normalized_api = normalized_base + "/w/api.php"
        return cls(
            gate_id=normalized_id,
            name=(name or normalized_id).strip(),
            engine=normalized_engine,
            base_url=normalized_base,
            api_url=normalized_api,
            language=str(language).strip(),
            builtin=bool(builtin),
            template=bool(template),
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class GateCatalog:
    WIKIMEDIA_FAMILIES = {
        "wikipedia": "wikipedia.org",
        "wiktionary": "wiktionary.org",
        "wikibooks": "wikibooks.org",
        "wikinews": "wikinews.org",
        "wikiquote": "wikiquote.org",
        "wikisource": "wikisource.org",
        "wikiversity": "wikiversity.org",
        "wikivoyage": "wikivoyage.org",
    }

    ENGINES = (
        "mediawiki",
        "wikidata",
        "dokuwiki",
        "moinmoin",
        "xwiki",
        "twiki",
        "foswiki",
        "pmwiki",
        "tiddlywiki",
        "wikijs",
        "bookstack",
        "gollum",
        "ikiwiki",
        "gitit",
        "oddmuse",
        "tikiwiki",
        "confluence",
    )

    def __init__(self, custom: Mapping[str, GateSpec] | None = None) -> None:
        self._custom = dict(custom or {})
        self._named = _named_gates()

    def resolve(self, gate_id: str) -> GateSpec:
        key = _validate_gate_id(gate_id)
        if key in self._custom:
            return self._custom[key]
        if key in self._named:
            return self._named[key]

        parts = key.split(":")
        if len(parts) == 2 and parts[0] in self.WIKIMEDIA_FAMILIES:
            family, language = parts
            if not _LANGUAGE.match(language):
                raise WikiGateError(f"invalid wiki language {language!r}", kind="invalid_gate")
            domain = self.WIKIMEDIA_FAMILIES[family]
            return GateSpec.custom(
                key,
                f"https://{language}.{domain}",
                engine="mediawiki",
                name=f"{family} ({language})",
                api_url=f"https://{language}.{domain}/w/api.php",
                language=language,
                builtin=True,
            )

        if len(parts) == 3 and parts[0] == "wikimedia" and parts[1] in self.WIKIMEDIA_FAMILIES:
            return self.resolve(f"{parts[1]}:{parts[2]}")

        raise WikiGateError(f"unknown wiki gate {gate_id!r}", kind="unknown_gate")

    def named(self) -> list[dict[str, Any]]:
        values = list(self._named.values()) + list(self._custom.values())
        values.sort(key=lambda item: item.gate_id)
        return [item.as_dict() for item in values]

    def families(self) -> list[dict[str, Any]]:
        values = [
            {
                "gate": f"{family}:<language>",
                "engine": "mediawiki",
                "kind": "wikimedia-language-family",
                "domain": domain,
            }
            for family, domain in sorted(self.WIKIMEDIA_FAMILIES.items())
        ]
        values.extend(
            {
                "gate": f"custom:<id>",
                "engine": engine,
                "kind": "operator-defined",
                "domain": "",
            }
            for engine in self.ENGINES
        )
        return values

    def describe(self) -> dict[str, Any]:
        return {
            "named": self.named(),
            "families": self.families(),
            "engines": list(self.ENGINES),
        }


class MediaWikiGate:
    name = "wiki"
    local = False

    def __init__(
        self,
        spec: GateSpec,
        *,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 2 * 1024 * 1024,
        opener: Callable[..., Any] = urllib.request.urlopen,
    ) -> None:
        if spec.engine not in {"mediawiki", "wikidata"}:
            raise WikiGateError(
                f"gate {spec.gate_id!r} does not expose a MediaWiki Action API",
                kind="unsupported_engine",
            )
        self.spec = spec
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = int(max_response_bytes)
        self.opener = opener

    def search(self, query: str, *, count: int = 5, **parameters: Any) -> list[SourcedResult]:
        _validate_query(query)
        _validate_count(count)
        payload = self._request(
            {
                "action": "query",
                "list": "search",
                "srsearch": query.strip(),
                "srlimit": count,
                "srprop": "snippet|timestamp",
                "format": "json",
                "formatversion": 2,
            }
        )
        raw_results = payload.get("query", {}).get("search", [])
        if not isinstance(raw_results, list):
            raise WikiGateError("MediaWiki search response is malformed", kind="malformed_response")
        results: list[SourcedResult] = []
        for item in raw_results[:count]:
            if not isinstance(item, dict):
                raise WikiGateError("MediaWiki search result is malformed", kind="malformed_response")
            page_id = item.get("pageid")
            title = str(item.get("title") or "")
            if isinstance(page_id, bool) or not isinstance(page_id, int) or not title:
                raise WikiGateError("MediaWiki search result is missing page identity", kind="malformed_response")
            results.append(
                SourcedResult(
                    provider="wiki",
                    url=f"{self.spec.base_url}/?curid={page_id}",
                    title=title,
                    excerpt=_clean_markup(str(item.get("snippet") or "")),
                    timestamp=str(item.get("timestamp") or ""),
                    local=False,
                    gate=self.spec.gate_id,
                )
            )
        return results

    def fetch_page(self, title: str) -> dict[str, Any]:
        if not isinstance(title, str) or not title.strip() or len(title) > 1024:
            raise ValueError("title must contain 1 to 1024 characters")
        payload = self._request(
            {
                "action": "query",
                "titles": title.strip(),
                "redirects": 1,
                "prop": "info|revisions|categories|links|pageprops",
                "inprop": "url",
                "rvprop": "ids|timestamp|content",
                "rvslots": "main",
                "cllimit": 100,
                "pllimit": 100,
                "format": "json",
                "formatversion": 2,
            }
        )
        pages = payload.get("query", {}).get("pages", [])
        if not isinstance(pages, list) or not pages:
            raise WikiGateError("MediaWiki page response is malformed", kind="malformed_response")
        page = pages[0]
        if not isinstance(page, dict):
            raise WikiGateError("MediaWiki page response is malformed", kind="malformed_response")
        if page.get("missing") is not None:
            raise WikiGateError(f"page {title!r} was not found", kind="not_found")

        page_id = page.get("pageid")
        if isinstance(page_id, bool) or not isinstance(page_id, int):
            raise WikiGateError("MediaWiki page is missing pageid", kind="malformed_response")
        revisions = page.get("revisions") or []
        revision = revisions[0] if isinstance(revisions, list) and revisions else {}
        if not isinstance(revision, dict):
            raise WikiGateError("MediaWiki revision is malformed", kind="malformed_response")
        slots = revision.get("slots") or {}
        main = slots.get("main") if isinstance(slots, dict) else {}
        if not isinstance(main, dict):
            main = {}
        content = main.get("content")
        if content is None:
            content = revision.get("*", "")
        categories = _titles(page.get("categories"))
        links = _titles(page.get("links"))
        pageprops = page.get("pageprops") or {}
        wikidata_id = str(pageprops.get("wikibase_item") or "") if isinstance(pageprops, dict) else ""
        canonical_url = str(page.get("fullurl") or f"{self.spec.base_url}/?curid={page_id}")
        _validate_result_url(canonical_url)

        revision_id = revision.get("revid")
        if isinstance(revision_id, bool) or (revision_id is not None and not isinstance(revision_id, int)):
            raise WikiGateError("MediaWiki revision id is malformed", kind="malformed_response")

        return {
            "gate": self.spec.gate_id,
            "engine": self.spec.engine,
            "page_id": page_id,
            "title": str(page.get("title") or title.strip()),
            "canonical_url": canonical_url,
            "revision_id": revision_id,
            "revision_timestamp": str(revision.get("timestamp") or ""),
            "content": str(content or ""),
            "categories": categories,
            "links": links,
            "wikidata_id": wikidata_id,
        }

    def _request(self, parameters: Mapping[str, Any]) -> dict[str, Any]:
        if not self.spec.api_url:
            raise WikiGateError(f"gate {self.spec.gate_id!r} has no native API", kind="unsupported_engine")
        separator = "&" if "?" in self.spec.api_url else "?"
        url = self.spec.api_url + separator + urllib.parse.urlencode(parameters)
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "zara-knowledge/0.2 (+https://github.com/lost-rob0t/zara-plugins)",
            },
            method="GET",
        )
        try:
            with self.opener(request, timeout=self.timeout_seconds) as response:
                status = int(getattr(response, "status", 200))
                if status < 200 or status >= 300:
                    raise WikiGateError(f"MediaWiki returned HTTP {status}", kind="http_error")
                raw = response.read(self.max_response_bytes + 1)
        except WikiGateError:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise WikiGateError(f"MediaWiki request failed: {error}", kind="transport_error") from error
        if len(raw) > self.max_response_bytes:
            raise WikiGateError("MediaWiki response exceeded configured size bound", kind="response_too_large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise WikiGateError("MediaWiki returned malformed JSON", kind="malformed_response") from error
        if not isinstance(payload, dict):
            raise WikiGateError("MediaWiki returned a non-object response", kind="malformed_response")
        api_error = payload.get("error")
        if isinstance(api_error, dict):
            code = str(api_error.get("code") or "api_error")
            raise WikiGateError(f"MediaWiki API error: {code}", kind="api_error")
        return payload


class SiteSearchGate:
    local = False

    def __init__(self, spec: GateSpec, provider: Any) -> None:
        self.spec = spec
        self.provider = provider
        self.name = f"wiki:{spec.gate_id}"

    def search(self, query: str, *, count: int = 5, **parameters: Any) -> list[SourcedResult]:
        host = urllib.parse.urlsplit(self.spec.base_url).hostname
        results = self.provider.search(f"site:{host} {query}", count=count, **parameters)
        return [
            SourcedResult(
                provider="wiki-site-search",
                url=item.url,
                title=item.title,
                excerpt=item.excerpt,
                timestamp=item.timestamp,
                local=item.local,
                gate=self.spec.gate_id,
            )
            for item in results
        ]

    def fetch_page(self, title: str) -> dict[str, Any]:
        raise WikiGateError(
            f"gate {self.spec.gate_id!r} does not expose a supported import API",
            kind="unsupported_import",
        )


class WikiManager:
    def __init__(
        self,
        catalog: GateCatalog,
        store: WikiStore,
        *,
        gate_factory: Callable[[GateSpec], Any] | None = None,
        site_search_provider: Any | None = None,
        max_gates: int = 4,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.catalog = catalog
        self.store = store
        self.gate_factory = gate_factory
        self.site_search_provider = site_search_provider
        self.max_gates = int(max_gates)
        self.timeout_seconds = float(timeout_seconds)
        self.max_response_bytes = int(max_response_bytes)

    def search(
        self,
        query: str,
        gate_ids: Iterable[str],
        *,
        count: int = 5,
        **parameters: Any,
    ) -> dict[str, Any]:
        _validate_query(query)
        _validate_count(count)
        selected = _normalize_gate_ids(gate_ids)
        if not selected:
            raise ValueError("at least one wiki gate is required")
        if len(selected) > self.max_gates:
            raise ValueError(f"wiki search accepts at most {self.max_gates} gates per request")

        results: list[SourcedResult] = []
        errors: list[dict[str, str]] = []
        for gate_id in selected:
            spec = self.catalog.resolve(gate_id)
            try:
                gate = self._build_gate(spec)
                results.extend(gate.search(query.strip(), count=count, **parameters))
            except Exception as error:
                errors.append(
                    {
                        "gate": gate_id,
                        "provider": "wiki",
                        "kind": str(getattr(error, "kind", "unavailable")),
                        "message": str(error),
                    }
                )
        return {
            "query": query.strip(),
            "gates": selected,
            "results": [result.as_dict() for result in results[:count]],
            "errors": errors,
        }

    def import_page(self, gate_id: str, title: str) -> dict[str, Any]:
        spec = self.catalog.resolve(gate_id)
        gate = self._build_gate(spec)
        page = gate.fetch_page(title)
        stored = self.store.upsert(page)
        stored["engine"] = spec.engine
        stored["imported"] = True
        return stored

    def local_search(
        self,
        query: str,
        *,
        count: int = 5,
        gate_ids: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        selected = _normalize_gate_ids(gate_ids or ())
        results = self.store.search(query, count=count, gates=selected)
        return {
            "query": query.strip(),
            "gates": selected,
            "results": [item.as_dict() for item in results],
            "errors": [],
        }

    def status(self) -> dict[str, Any]:
        return {
            "store_pages": self.store.count(),
            "max_gates": self.max_gates,
            "catalog": self.catalog.describe(),
        }

    def _build_gate(self, spec: GateSpec) -> Any:
        if self.gate_factory is not None:
            return self.gate_factory(spec)
        if spec.engine in {"mediawiki", "wikidata"}:
            return MediaWikiGate(
                spec,
                timeout_seconds=self.timeout_seconds,
                max_response_bytes=self.max_response_bytes,
            )
        if self.site_search_provider is not None:
            return SiteSearchGate(spec, self.site_search_provider)
        raise WikiGateError(
            f"gate {spec.gate_id!r} requires a configured site-search provider",
            kind="unsupported_engine",
        )


def custom_specs(mapping: Mapping[str, Any] | None) -> dict[str, GateSpec]:
    if mapping is None:
        return {}
    if not isinstance(mapping, Mapping):
        raise WikiGateError("wiki_gates must be a mapping", kind="invalid_gate")
    result: dict[str, GateSpec] = {}
    for gate_id, raw in mapping.items():
        if not isinstance(raw, Mapping):
            raise WikiGateError(f"wiki gate {gate_id!r} must be a mapping", kind="invalid_gate")
        result[str(gate_id)] = GateSpec.custom(
            str(gate_id),
            str(raw.get("base_url") or ""),
            engine=str(raw.get("engine") or "mediawiki"),
            name=str(raw.get("name") or ""),
            api_url=str(raw.get("api_url") or ""),
            language=str(raw.get("language") or ""),
        )
    return result


def parse_gate_ids(value: str | Iterable[str] | None) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = value.split(",")
    else:
        items = list(value)
    return _normalize_gate_ids(items)


def _named_gates() -> dict[str, GateSpec]:
    definitions = (
        ("wikidata", "Wikidata", "wikidata", "https://www.wikidata.org", "https://www.wikidata.org/w/api.php"),
        ("commons", "Wikimedia Commons", "mediawiki", "https://commons.wikimedia.org", "https://commons.wikimedia.org/w/api.php"),
        ("meta", "Meta-Wiki", "mediawiki", "https://meta.wikimedia.org", "https://meta.wikimedia.org/w/api.php"),
        ("mediawiki", "MediaWiki.org", "mediawiki", "https://www.mediawiki.org", "https://www.mediawiki.org/w/api.php"),
        ("species", "Wikispecies", "mediawiki", "https://species.wikimedia.org", "https://species.wikimedia.org/w/api.php"),
        ("wikifunctions", "Wikifunctions", "mediawiki", "https://www.wikifunctions.org", "https://www.wikifunctions.org/w/api.php"),
        ("archwiki", "ArchWiki", "mediawiki", "https://wiki.archlinux.org", "https://wiki.archlinux.org/api.php"),
        ("nixos-wiki", "Official NixOS Wiki", "mediawiki", "https://wiki.nixos.org", "https://wiki.nixos.org/w/api.php"),
        ("gentoo-wiki", "Gentoo Wiki", "mediawiki", "https://wiki.gentoo.org", "https://wiki.gentoo.org/api.php"),
        ("debian-wiki", "Debian Wiki", "moinmoin", "https://wiki.debian.org", ""),
        ("ubuntu-wiki", "Ubuntu Wiki", "moinmoin", "https://wiki.ubuntu.com", ""),
        ("emacswiki", "EmacsWiki", "oddmuse", "https://www.emacswiki.org", ""),
        ("rosettacode", "Rosetta Code", "mediawiki", "https://rosettacode.org", "https://rosettacode.org/w/api.php"),
    )
    return {
        gate_id: GateSpec.custom(
            gate_id,
            base_url,
            engine=engine,
            name=name,
            api_url=api_url,
            builtin=True,
        )
        for gate_id, name, engine, base_url, api_url in definitions
    }


def _validate_gate_id(gate_id: str) -> str:
    value = str(gate_id).strip().lower()
    if not _GATE_ID.match(value):
        raise WikiGateError(f"invalid wiki gate id {gate_id!r}", kind="invalid_gate")
    return value


def _validate_base_url(url: str) -> str:
    value = str(url).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.username is not None or parsed.password is not None:
        raise WikiGateError("wiki gate URLs must not contain credentials", kind="invalid_gate")
    if not parsed.hostname:
        raise WikiGateError("wiki gate URL must contain a host", kind="invalid_gate")
    if parsed.scheme == "https":
        return value
    if parsed.scheme == "http" and _loopback(parsed.hostname):
        return value
    raise WikiGateError("wiki gate URLs must use https except for loopback hosts", kind="invalid_gate")


def _validate_api_url(api_url: str, base_url: str) -> str:
    value = _validate_base_url(api_url)
    base_host = urllib.parse.urlsplit(base_url).hostname
    api_host = urllib.parse.urlsplit(value).hostname
    if base_host != api_host:
        raise WikiGateError("wiki gate API host must match the gate host", kind="invalid_gate")
    return value


def _validate_result_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise WikiGateError("wiki result URL is invalid", kind="malformed_response")
    if parsed.username is not None or parsed.password is not None:
        raise WikiGateError("wiki result URL contains credentials", kind="malformed_response")


def _loopback(host: str) -> bool:
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _validate_query(query: str) -> None:
    if not isinstance(query, str) or not query.strip() or len(query) > 2048:
        raise ValueError("query must contain 1 to 2048 characters")


def _validate_count(count: int) -> None:
    if not isinstance(count, int) or isinstance(count, bool) or not 1 <= count <= 20:
        raise ValueError("count must be between 1 and 20")


def _normalize_gate_ids(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        gate_id = _validate_gate_id(str(value))
        if gate_id not in result:
            result.append(gate_id)
    return result


def _clean_markup(value: str) -> str:
    return " ".join(html.unescape(_TAGS.sub(" ", value)).split())


def _titles(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise WikiGateError("MediaWiki list property is malformed", kind="malformed_response")
    result: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            raise WikiGateError("MediaWiki list item is malformed", kind="malformed_response")
        title = item.get("title")
        if isinstance(title, str) and title:
            result.append(title)
    return result
