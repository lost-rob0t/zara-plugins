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

    def write(self, plugin_search_paths, **overrides) -> None:
        document = {
            "schema_version": 1,
            "updated": "2026-09-06",
            "registry": "https://github.com/lost-rob0t/zara-plugins",
            "registry_raw": "https://raw.githubusercontent.com/lost-rob0t/zara-plugins/main/plugins.json",
            "plugin_search_paths": plugin_search_paths,
            "plugins": [],
        }
        document.update(overrides)
        self.registry.write_text(json.dumps(document), encoding="utf-8")

    def test_plugin_search_paths_must_be_nonempty_strings(self) -> None:
        self.write(["~/.zarathushtra/plugins", " "])
        with self.assertRaisesRegex(validate_registry.RegistryError, "plugin_search_paths"):
            validate_registry.load_registry()

    def test_plugin_search_paths_must_not_contain_surrounding_whitespace(self) -> None:
        self.write([" ~/.zarathushtra/plugins "])
        with self.assertRaisesRegex(validate_registry.RegistryError, "plugin_search_paths"):
            validate_registry.load_registry()

    def test_plugin_search_paths_must_not_contain_duplicates(self) -> None:
        self.write(["~/.zarathushtra/plugins", "~/.zarathushtra/plugins"])
        with self.assertRaisesRegex(validate_registry.RegistryError, "plugin_search_paths"):
            validate_registry.load_registry()

    def test_registry_url_must_name_canonical_repository(self) -> None:
        self.write(["~/.zarathushtra/plugins"], registry="https://example.invalid/plugins")
        with self.assertRaisesRegex(validate_registry.RegistryError, "registry URL"):
            validate_registry.load_registry()

    def test_registry_raw_url_must_name_canonical_main_catalog(self) -> None:
        self.write(["~/.zarathushtra/plugins"], registry_raw="https://example.invalid/plugins.json")
        with self.assertRaisesRegex(validate_registry.RegistryError, "registry_raw"):
            validate_registry.load_registry()


if __name__ == "__main__":
    unittest.main()
