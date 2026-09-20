import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_knowledge.core import SourcedResult
from zara_knowledge.store import WikiStore
from zara_knowledge.wiki import (
    GateCatalog,
    GateSpec,
    MediaWikiGate,
    WikiGateError,
    WikiManager,
)


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit=-1):
        data = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
        return data if limit < 0 else data[:limit]


class QueueOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class GateCatalogTest(unittest.TestCase):
    def test_wikimedia_families_resolve_any_language_without_hardcoding(self):
        catalog = GateCatalog()
        enwiki = catalog.resolve("wikipedia:en")
        frdict = catalog.resolve("wiktionary:fr")
        voyage = catalog.resolve("wikivoyage:de")

        self.assertEqual(enwiki.base_url, "https://en.wikipedia.org")
        self.assertEqual(frdict.base_url, "https://fr.wiktionary.org")
        self.assertEqual(voyage.base_url, "https://de.wikivoyage.org")
        self.assertEqual(enwiki.engine, "mediawiki")

    def test_global_wikimedia_projects_are_named_gates(self):
        catalog = GateCatalog()
        expected = {
            "wikidata": "https://www.wikidata.org",
            "commons": "https://commons.wikimedia.org",
            "meta": "https://meta.wikimedia.org",
            "mediawiki": "https://www.mediawiki.org",
            "species": "https://species.wikimedia.org",
            "wikifunctions": "https://www.wikifunctions.org",
        }
        for gate_id, url in expected.items():
            with self.subTest(gate_id=gate_id):
                self.assertEqual(catalog.resolve(gate_id).base_url, url)

    def test_engine_families_are_exposed_as_gate_templates(self):
        families = {item["engine"] for item in GateCatalog().families()}
        self.assertTrue(
            {
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
            }.issubset(families)
        )

    def test_custom_gate_rejects_credentials_and_unsafe_remote_http(self):
        with self.assertRaisesRegex(WikiGateError, "credentials"):
            GateSpec.custom("bad", "https://user:pass@example.test", engine="mediawiki")
        with self.assertRaisesRegex(WikiGateError, "https"):
            GateSpec.custom("bad", "http://example.test", engine="mediawiki")

        local = GateSpec.custom("local", "http://127.0.0.1:8080", engine="mediawiki")
        self.assertEqual(local.base_url, "http://127.0.0.1:8080")


class MediaWikiGateTest(unittest.TestCase):
    def test_search_maps_mediawiki_hits_to_sourced_results(self):
        opener = QueueOpener(
            [
                FakeResponse(
                    {
                        "query": {
                            "search": [
                                {
                                    "pageid": 42,
                                    "title": "Actor model",
                                    "snippet": "message <span class=\"searchmatch\">passing</span>",
                                    "timestamp": "2026-09-19T00:00:00Z",
                                }
                            ]
                        }
                    }
                )
            ]
        )
        gate = MediaWikiGate(
            GateSpec.custom("testwiki", "https://example.test", engine="mediawiki"),
            opener=opener,
        )

        results = gate.search("actor model", count=3)

        self.assertEqual(len(results), 1)
        self.assertIsInstance(results[0], SourcedResult)
        self.assertEqual(results[0].provider, "wiki")
        self.assertEqual(results[0].gate, "testwiki")
        self.assertEqual(results[0].url, "https://example.test/?curid=42")
        self.assertNotIn("<span", results[0].excerpt)
        self.assertIn("passing", results[0].excerpt)

        request_url = opener.requests[0].full_url
        self.assertIn("list=search", request_url)
        self.assertIn("srsearch=actor+model", request_url)

    def test_fetch_page_preserves_revision_and_source_provenance(self):
        opener = QueueOpener(
            [
                FakeResponse(
                    {
                        "query": {
                            "pages": [
                                {
                                    "pageid": 7,
                                    "title": "Common Lisp",
                                    "fullurl": "https://example.test/wiki/Common_Lisp",
                                    "categories": [{"title": "Category:Lisp"}],
                                    "links": [{"title": "Lisp (programming language)"}],
                                    "pageprops": {"wikibase_item": "Q123"},
                                    "revisions": [
                                        {
                                            "revid": 99,
                                            "timestamp": "2026-09-19T01:02:03Z",
                                            "slots": {"main": {"content": "Common Lisp source text"}},
                                        }
                                    ],
                                }
                            ]
                        }
                    }
                )
            ]
        )
        gate = MediaWikiGate(
            GateSpec.custom("testwiki", "https://example.test", engine="mediawiki"),
            opener=opener,
        )

        page = gate.fetch_page("Common Lisp")

        self.assertEqual(page["gate"], "testwiki")
        self.assertEqual(page["page_id"], 7)
        self.assertEqual(page["revision_id"], 99)
        self.assertEqual(page["revision_timestamp"], "2026-09-19T01:02:03Z")
        self.assertEqual(page["canonical_url"], "https://example.test/wiki/Common_Lisp")
        self.assertEqual(page["content"], "Common Lisp source text")
        self.assertEqual(page["wikidata_id"], "Q123")
        self.assertEqual(page["categories"], ["Category:Lisp"])
        self.assertEqual(page["links"], ["Lisp (programming language)"])


class WikiStoreTest(unittest.TestCase):
    def test_imported_pages_are_locally_searchable_with_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WikiStore(Path(directory) / "wiki.sqlite3")
            store.upsert(
                {
                    "gate": "wikipedia:en",
                    "page_id": 12,
                    "title": "Actor model",
                    "canonical_url": "https://en.wikipedia.org/wiki/Actor_model",
                    "revision_id": 44,
                    "revision_timestamp": "2026-09-19T00:00:00Z",
                    "content": "The actor model uses asynchronous message passing.",
                    "categories": ["Category:Concurrency"],
                    "links": ["Erlang"],
                    "wikidata_id": "Q123",
                }
            )

            result = store.search("message passing", count=5)

            self.assertEqual(len(result), 1)
            self.assertEqual(result[0].provider, "wiki-import")
            self.assertEqual(result[0].gate, "wikipedia:en")
            self.assertTrue(result[0].local)
            stored = store.get("wikipedia:en", 12)
            self.assertEqual(stored["revision_id"], 44)
            self.assertEqual(stored["wikidata_id"], "Q123")


class FakeGate:
    def __init__(self, spec, results=None, page=None, error=None):
        self.spec = spec
        self.name = f"wiki:{spec.gate_id}"
        self.results = list(results or [])
        self.page = page
        self.error = error

    def search(self, query, *, count=5, **parameters):
        if self.error:
            raise self.error
        return self.results[:count]

    def fetch_page(self, title):
        if self.error:
            raise self.error
        return dict(self.page)


class WikiManagerTest(unittest.TestCase):
    def test_selected_gates_only_and_failures_degrade_independently(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WikiStore(Path(directory) / "wiki.sqlite3")
            catalog = GateCatalog(
                custom={
                    "one": GateSpec.custom("one", "https://one.example", engine="mediawiki"),
                    "two": GateSpec.custom("two", "https://two.example", engine="mediawiki"),
                    "three": GateSpec.custom("three", "https://three.example", engine="mediawiki"),
                }
            )
            made = []

            def factory(spec):
                made.append(spec.gate_id)
                if spec.gate_id == "two":
                    return FakeGate(spec, error=WikiGateError("two failed", kind="upstream"))
                return FakeGate(
                    spec,
                    results=[
                        SourcedResult(
                            "wiki",
                            f"https://{spec.gate_id}.example/page",
                            spec.gate_id,
                            "hit",
                            "2026-09-19T00:00:00Z",
                            False,
                            gate=spec.gate_id,
                        )
                    ],
                )

            manager = WikiManager(catalog, store, gate_factory=factory, max_gates=2)
            result = manager.search("query", ["one", "two"], count=5)

            self.assertEqual(made, ["one", "two"])
            self.assertEqual(result["results"][0]["gate"], "one")
            self.assertEqual(result["errors"][0]["gate"], "two")
            self.assertNotIn("three", made)

    def test_gate_fanout_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WikiStore(Path(directory) / "wiki.sqlite3")
            manager = WikiManager(GateCatalog(), store, max_gates=2)
            with self.assertRaisesRegex(ValueError, "at most 2"):
                manager.search("query", ["wikipedia:en", "wikipedia:fr", "wikipedia:de"])

    def test_import_writes_fetched_page_to_local_store(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WikiStore(Path(directory) / "wiki.sqlite3")
            spec = GateSpec.custom("one", "https://one.example", engine="mediawiki")
            catalog = GateCatalog(custom={"one": spec})
            page = {
                "gate": "one",
                "page_id": 5,
                "title": "Page",
                "canonical_url": "https://one.example/wiki/Page",
                "revision_id": 8,
                "revision_timestamp": "2026-09-19T00:00:00Z",
                "content": "stored body",
                "categories": [],
                "links": [],
                "wikidata_id": "",
            }
            manager = WikiManager(
                catalog,
                store,
                gate_factory=lambda resolved: FakeGate(resolved, page=page),
            )

            imported = manager.import_page("one", "Page")

            self.assertEqual(imported["page_id"], 5)
            self.assertEqual(store.get("one", 5)["content"], "stored body")


if __name__ == "__main__":
    unittest.main()
