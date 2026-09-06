import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_memory.domain import MemoryError, MemoryService, MemorySchema


class FakeBackend:
    pass


class SchemaRegistrationTypeTests(unittest.TestCase):
    def test_rejects_non_schema_objects_without_mutating_registry(self):
        service = MemoryService(FakeBackend())

        for schema in (None, 7, {}, object()):
            with self.subTest(schema=schema):
                with self.assertRaises(MemoryError):
                    service.register_schema(schema)

        valid = MemorySchema(
            name="coding.workflow",
            allowed_scopes=frozenset({"project"}),
            allowed_fact_predicates=frozenset({"workflow_state"}),
        )
        service.register_schema(valid)

        with self.assertRaisesRegex(MemoryError, "already registered"):
            service.register_schema(valid)


if __name__ == "__main__":
    unittest.main()
