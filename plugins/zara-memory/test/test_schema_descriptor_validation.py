import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemorySchema


class SchemaDescriptorValidationTests(unittest.TestCase):
    def test_rejects_malformed_schema_names_with_value_error(self):
        for name in (7, [], "", " " * 129):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    MemorySchema(
                        name=name,
                        allowed_scopes=frozenset({"project"}),
                        allowed_fact_predicates=frozenset({"workflow_state"}),
                    )

    def test_rejects_noncanonical_scope_collections(self):
        for scopes in (["project"], {"project"}, frozenset({7}), frozenset({""})):
            with self.subTest(scopes=scopes):
                with self.assertRaises(ValueError):
                    MemorySchema(
                        name="coding.workflow",
                        allowed_scopes=scopes,
                        allowed_fact_predicates=frozenset({"workflow_state"}),
                    )

    def test_rejects_noncanonical_predicate_collections(self):
        for predicates in (["workflow_state"], {"workflow_state"}, frozenset({7}), frozenset({""})):
            with self.subTest(predicates=predicates):
                with self.assertRaises(ValueError):
                    MemorySchema(
                        name="coding.workflow",
                        allowed_scopes=frozenset({"project"}),
                        allowed_fact_predicates=predicates,
                    )


if __name__ == "__main__":
    unittest.main()
