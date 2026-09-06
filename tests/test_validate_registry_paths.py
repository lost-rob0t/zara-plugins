from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate-registry.py"
SPEC = importlib.util.spec_from_file_location("validate_registry", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validate_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_registry)


class RegistryPathConfinementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.plugins = self.root / "plugins"
        self.plugin = self.plugins / "example"
        self.plugin.mkdir(parents=True)
        self.entrypoint = self.plugin / "entrypoint.py"
        self.entrypoint.write_text(
            "from object import object\n"
            "VERSION = '0.1.0'\n"
            "def create_plugin():\n"
            "    return None\n",
            encoding="utf-8",
        )
        self.docs = self.plugin / "README.md"
        self.docs.write_text("# Example\n", encoding="utf-8")
        self.previous_root = validate_registry.ROOT
        self.previous_plugins = validate_registry.PLUGINS_DIR
        validate_registry.ROOT = self.root
        validate_registry.PLUGINS_DIR = self.plugins

    def tearDown(self) -> None:
        validate_registry.ROOT = self.previous_root
        validate_registry.PLUGINS_DIR = self.previous_plugins
        self.temporary.cleanup()

    def entry(self) -> dict:
        return {
            "name": "example",
            "version": "0.1.0",
            "api_version": "1",
            "plugin_type": "service",
            "description": "example",
            "path": "plugins/example",
            "entrypoint": "entrypoint.py",
            "docs": "plugins/example/README.md",
            "license": "GPL-3.0-or-later",
        }

    def test_entrypoint_must_stay_inside_plugin_directory(self) -> None:
        outside = self.plugins / "outside.py"
        outside.write_text("VERSION = '0.1.0'\ndef create_plugin(): return None\n", encoding="utf-8")
        entry = self.entry()
        entry["entrypoint"] = "../outside.py"
        with self.assertRaisesRegex(validate_registry.RegistryError, "entrypoint must stay inside"):
            validate_registry.validate_entry(entry)

    def test_docs_must_stay_inside_plugin_directory(self) -> None:
        outside = self.plugins / "outside.md"
        outside.write_text("outside\n", encoding="utf-8")
        entry = self.entry()
        entry["docs"] = "plugins/example/../outside.md"
        with self.assertRaisesRegex(validate_registry.RegistryError, "docs must stay inside"):
            validate_registry.validate_entry(entry)


if __name__ == "__main__":
    unittest.main()
