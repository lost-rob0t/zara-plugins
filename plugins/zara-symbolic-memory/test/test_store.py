import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_symbolic_memory.store import SymbolicMemoryStore, _split_prolog_clauses


class FakeEmbedder:
    model = "fake-3"

    def embed(self, texts):
        return [[float(len(text) % 7), 1.0, 0.5] for text in texts]


class Clock:
    def __init__(self):
        self.now = 1_700_000_000

    def __call__(self):
        return self.now


class SymbolicMemoryStoreTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.clock = Clock()
        self.store = SymbolicMemoryStore(self.temp.name, embedder=FakeEmbedder(), clock=self.clock)

    def tearDown(self):
        self.temp.cleanup()

    def test_symbolic_fact_is_canonical_and_embedding_is_derived(self):
        result = self.store.remember(subject="user", predicate="likes", object_json=json.dumps("red"), source="explicit-user")
        memory_text = self.store.memory_path.read_text(encoding="utf-8")
        embedding_text = self.store.embeddings_path.read_text(encoding="utf-8")
        self.assertIn("memory_fact(", memory_text)
        self.assertIn('"explicit-user"', memory_text)
        self.assertIn("memory_embedding(", embedding_text)
        self.assertEqual(result["embedding"], "indexed")

    def test_same_symbolic_slot_versions_instead_of_creating_an_opaque_duplicate(self):
        first = self.store.remember(subject="user", predicate="likes", object_json='"red"')
        second = self.store.remember(subject="user", predicate="likes", object_json='"blue"')
        self.assertEqual(first["memory_id"], second["memory_id"])
        self.assertEqual(second["version"], 2)
        self.assertEqual([record.object_json for record in self.store.records()], ['"red"', '"blue"'])

    def test_forget_appends_tombstone(self):
        result = self.store.remember(subject="user", predicate="likes", object_json='"red"')
        forgotten = self.store.forget(result["memory_id"], reason="requested")
        self.assertEqual(forgotten["version"], 2)
        self.assertIn("memory_tombstone(", self.store.memory_path.read_text(encoding="utf-8"))

    def test_rebuild_indexes_prolog_kb_into_prolog_embedding_facts(self):
        kb = Path(self.temp.name) / "kb"
        kb.mkdir()
        (kb / "facts.pl").write_text("likes(user, red).\nrule(X) :- likes(X, red).\n", encoding="utf-8")
        self.store.remember(subject="user", predicate="likes", object_json='"red"')
        result = self.store.rebuild_embeddings([kb])
        text = self.store.embeddings_path.read_text(encoding="utf-8")
        self.assertEqual(result["kb_clauses"], 2)
        self.assertIn("kb_clause(", text)
        self.assertIn("kb_embedding(", text)
        self.assertIn("memory_embedding(", text)

    def test_clause_splitter_preserves_dots_inside_quotes_and_nested_terms(self):
        clauses = _split_prolog_clauses('url("https://example.test/a.b").\nthing(foo(bar.baz)).\n')
        self.assertEqual(len(clauses), 2)


if __name__ == "__main__":
    unittest.main()
