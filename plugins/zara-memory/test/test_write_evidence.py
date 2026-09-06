import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemorySchema, MemoryService


class MutatingBackend:
    def __init__(self, field):
        self.field = field

    def remember(self, **kwargs):
        item = {
            "id": "memory-1",
            "scope": kwargs["scope"],
            "owner": kwargs["owner"],
            "text": kwargs["text"],
            "facts": list(kwargs["facts"]),
            "provenance": dict(kwargs["provenance"]),
            "type": kwargs["memory_type"],
            "created_at": "2026-09-06T00:00:00Z",
        }
        if self.field == "text":
            item["text"] = "rewritten"
        elif self.field == "facts":
            item["facts"] = ["workflow_state(build)"]
        elif self.field == "provenance":
            item["provenance"] = {"source": "rewritten"}
        return item


class InPlaceProvenanceMutatingBackend:
    def remember(self, **kwargs):
        kwargs["provenance"]["source"] = "rewritten"
        kwargs["provenance"]["detail"]["message_id"] = "rewritten"
        return {
            "id": "memory-1",
            "scope": kwargs["scope"],
            "owner": kwargs["owner"],
            "text": kwargs["text"],
            "facts": list(kwargs["facts"]),
            "provenance": kwargs["provenance"],
            "type": kwargs["memory_type"],
            "created_at": "2026-09-06T00:00:00Z",
        }


class WriteEvidenceTests(unittest.TestCase):
    def memory(self, field):
        memory = MemoryService(MutatingBackend(field))
        memory.register_schema(
            MemorySchema(
                name="coding.workflow",
                allowed_scopes=frozenset({"project"}),
                allowed_fact_predicates=frozenset({"workflow_state"}),
            )
        )
        return memory

    def remember(self, field):
        return self.memory(field).remember(
            scope="project",
            owner="repo-a",
            text="original",
            facts=["workflow_state(verify)."],
            provenance={"source": "operator"},
            memory_type="coding.workflow",
        )

    def test_rejects_backend_mutation_of_write_evidence(self):
        for field in ("text", "facts", "provenance"):
            with self.subTest(field=field):
                with self.assertRaisesRegex(MemoryError, "write evidence"):
                    self.remember(field)

    def test_rejects_in_place_backend_mutation_of_nested_provenance(self):
        memory = MemoryService(InPlaceProvenanceMutatingBackend())
        memory.register_schema(
            MemorySchema(
                name="coding.workflow",
                allowed_scopes=frozenset({"project"}),
                allowed_fact_predicates=frozenset({"workflow_state"}),
            )
        )

        with self.assertRaisesRegex(MemoryError, "write evidence"):
            memory.remember(
                scope="project",
                owner="repo-a",
                text="original",
                facts=["workflow_state(verify)."],
                provenance={"source": "operator", "detail": {"message_id": "m-1"}},
                memory_type="coding.workflow",
            )

    def test_accepts_exact_normalized_write_evidence(self):
        result = self.remember(None)
        self.assertEqual(result["text"], "original")
        self.assertEqual(result["facts"], ["workflow_state(verify)"])
        self.assertEqual(result["provenance"], {"source": "operator"})


if __name__ == "__main__":
    unittest.main()
