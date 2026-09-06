from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate-registry.py"
SPEC = importlib.util.spec_from_file_location("validate_registry_updated", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validate_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_registry)


class RegistryUpdatedDateTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "plugins.json"
        self.previous_registry_path = validate_registry.REGISTRY_PATH
        validate_registry.REGISTRY_PATH = self.path

    def tearDown(self) -> None:
        validate_registry.REGISTRY_PATH = self.previous_registry_path
        self.temporary.cleanup()

    def write(self, updated) -> None:
        self.path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "updated": updated,
                    "registry": validate_registry.CANONICAL_REGISTRY_URL,
                    "registry_raw": validate_registry.CANONICAL_REGISTRY_RAW_URL,
                    "plugin_search_paths": ["~/.zarathushtra/plugins"],
                    "plugins": [],
                }
            ),
            encoding="utf-8",
        )

    def test_updated_requires_exact_calendar_date(self) -> None:
        for updated in (None, 20260906, "2026-9-6", " 2026-09-06 ", "2026-02-30"):
            with self.subTest(updated=updated):
                self.write(updated)
                with self.assertRaisesRegex(
                    validate_registry.RegistryError,
                    "updated.*YYYY-MM-DD",
                ):
                    validate_registry.load_registry()

    def test_updated_accepts_canonical_calendar_date(self) -> None:
        self.write("2026-09-06")
        document = validate_registry.load_registry()
        self.assertEqual(document["updated"], "2026-09-06")


if __name__ == "__main__":
    unittest.main()
