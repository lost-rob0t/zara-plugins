from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate-registry.py"
SPEC = importlib.util.spec_from_file_location("validate_registry", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validate_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_registry)


class RegistryDocumentMetadataTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.registry = Path(self.temporary.name) / "plugins.json"
        self.previous_registry = validate_registry.REGISTRY_PATH
        validate_registry.REGISTRY_PATH = self.registry

    def tearDown(self) -> None:
        validate_registry.REGISTRY_PATH = self.previous_registry
        self.temporary.cleanup()

    def write(self, plugin_search_paths) -> None:
        self.registry.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "plugin_search_paths": plugin_search_paths,
                    "plugins": [],
                }
            ),
            encoding="utf-8",
        )

    def test_plugin_search_paths_must_be_nonempty_strings(self) -> None:
        self.write(["~/.zarathushtra/plugins", " "])
        with self.assertRaisesRegex(validate_registry.RegistryError, "plugin_search_paths"):
            validate_registry.load_registry()

    def test_plugin_search_paths_must_not_contain_duplicates(self) -> None:
        self.write(["~/.zarathushtra/plugins", "~/.zarathushtra/plugins"])
        with self.assertRaisesRegex(validate_registry.RegistryError, "plugin_search_paths"):
            validate_registry.load_registry()


if __name__ == "__main__":
    unittest.main()
