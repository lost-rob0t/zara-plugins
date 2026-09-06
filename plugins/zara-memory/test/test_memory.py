import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemoryService, MemorySchema


class FakeBackend:
    def __init__(self):
        self.items = {}
        self.deleted = []
        self.counter = 0

    def remember(self, *, scope, owner, text, facts, provenance, memory_type):
        self.counter += 1
        memory_id = f"mem-{self.counter}"
        item = {"id": memory_id, "scope": scope, "owner": owner, "text": text, "facts": list(facts), "provenance": dict(provenance), "type": memory_type, "created_at": "2026-09-05T00:00:00Z"}
        self.items[memory_id] = item
        return dict(item)

    def recall(self, *, scope, owner, query=None, memory_type=None):
        return [dict(item) for item in self.items.values() if item["scope"] == scope and item["owner"] == owner and (memory_type is None or item["type"] == memory_type) and (query is None or query in item["text"])]

    def forget(self, *, memory_id, scope, owner):
        item = self.items.get(memory_id)
        if item is None or item["scope"] != scope or item["owner"] != owner:
            return {"removed": False, "projection_ids": []}
        self.items.pop(memory_id)
        self.deleted.append(memory_id)
        return {"removed": True, "projection_ids": [f"projection:{memory_id}"]}


class TypeConfusedBackend(FakeBackend):
    def remember(self, **kwargs):
        item = super().remember(**kwargs)
        item["type"] = "other.schema"
        return item

    def recall(self, **kwargs):
        items = super().recall(**kwargs)
        for item in items:
            item["type"] = "other.schema"
        return items


class MemoryServiceTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.memory = MemoryService(self.backend)
        self.memory.register_schema(MemorySchema(name="coding.workflow", allowed_scopes=frozenset({"project"}), allowed_fact_predicates=frozenset({"workflow_state", "verification"})))

    def test_scopes_are_isolated_by_scope_and_owner(self):
        one = self.memory.remember(scope="project", owner="repo-a", text="Use Prolog verification", facts=["workflow_state(verify)"], provenance={"source": "operator"}, memory_type="coding.workflow")
        self.memory.remember(scope="project", owner="repo-b", text="Different repo", facts=["workflow_state(build)"], provenance={"source": "operator"}, memory_type="coding.workflow")
        recalled = self.memory.recall(scope="project", owner="repo-a")
        self.assertEqual([item["id"] for item in recalled], [one["id"]])

    def test_full_text_provenance_and_stable_id_are_preserved(self):
        item = self.memory.remember(scope="project", owner="repo-a", text="Exact text — keep punctuation & whitespace.", facts=["verification(prolog)"], provenance={"source": "operator", "message_id": "m-1"}, memory_type="coding.workflow")
        recalled = self.memory.recall(scope="project", owner="repo-a")
        self.assertEqual(recalled[0]["id"], item["id"])
        self.assertEqual(recalled[0]["text"], "Exact text — keep punctuation & whitespace.")
        self.assertEqual(recalled[0]["provenance"]["message_id"], "m-1")

    def test_backend_cannot_change_type_on_remember(self):
        memory = MemoryService(TypeConfusedBackend())
        memory.register_schema(MemorySchema(name="coding.workflow", allowed_scopes=frozenset({"project"}), allowed_fact_predicates=frozenset({"workflow_state"})))
        with self.assertRaisesRegex(MemoryError, "memory type isolation"):
            memory.remember(scope="project", owner="repo-a", text="typed memory", facts=["workflow_state(verify)"], provenance={"source": "operator"}, memory_type="coding.workflow")

    def test_backend_cannot_change_type_on_typed_recall(self):
        backend = TypeConfusedBackend()
        backend.items["mem-1"] = {"id": "mem-1", "scope": "project", "owner": "repo-a", "text": "typed memory", "facts": ["workflow_state(verify)"], "provenance": {"source": "operator"}, "type": "coding.workflow", "created_at": "2026-09-05T00:00:00Z"}
        memory = MemoryService(backend)
        memory.register_schema(MemorySchema(name="coding.workflow", allowed_scopes=frozenset({"project"}), allowed_fact_predicates=frozenset({"workflow_state"})))
        with self.assertRaisesRegex(MemoryError, "memory type isolation"):
            memory.recall(scope="project", owner="repo-a", memory_type="coding.workflow")

    def test_schema_cannot_write_outside_registered_scope(self):
        with self.assertRaisesRegex(MemoryError, "scope"):
            self.memory.remember(scope="global", owner="global", text="bad", facts=["workflow_state(verify)"], provenance={"source": "plugin"}, memory_type="coding.workflow")

    def test_schema_rejects_unregistered_fact_predicate(self):
        with self.assertRaisesRegex(MemoryError, "predicate"):
            self.memory.remember(scope="project", owner="repo-a", text="bad", facts=["secret_token(value)"], provenance={"source": "plugin"}, memory_type="coding.workflow")

    def test_forget_requires_same_scope_and_cleans_projections(self):
        item = self.memory.remember(scope="project", owner="repo-a", text="temporary", facts=["workflow_state(plan)"], provenance={"source": "operator"}, memory_type="coding.workflow")
        wrong = self.memory.forget(item["id"], scope="project", owner="repo-b")
        self.assertFalse(wrong["removed"])
        result = self.memory.forget(item["id"], scope="project", owner="repo-a")
        self.assertTrue(result["removed"])
        self.assertEqual(result["projection_ids"], [f"projection:{item['id']}"])
        self.assertEqual(self.memory.recall(scope="project", owner="repo-a"), [])

    def test_transient_context_is_never_persisted_implicitly(self):
        self.memory.observe_context({"active_file": "/tmp/example.py"})
        self.assertEqual(self.backend.items, {})

    def test_all_initial_scopes_are_explicitly_supported(self):
        self.assertEqual(self.memory.supported_scopes, frozenset({"session", "user", "project", "machine", "global"}))


if __name__ == "__main__":
    unittest.main()
