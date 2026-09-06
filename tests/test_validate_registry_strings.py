from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate-registry.py"
SPEC = importlib.util.spec_from_file_location("validate_registry_strings", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validate_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_registry)


class RegistryCanonicalStringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.plugins = self.root / "plugins"
        self.plugin = self.plugins / "example"
        self.plugin.mkdir(parents=True)
        (self.plugin / "entrypoint.py").write_text(
            "VERSION = '0.1.0'\ndef create_plugin(): return None\n",
            encoding="utf-8",
        )
        (self.plugin / "README.md").write_text("# Example\n", encoding="utf-8")
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
            "tags": ["example"],
            "install": {"nix": "nix build github:lost-rob0t/zara-plugins#example"},
            "nix": {
                "flake": "github:lost-rob0t/zara-plugins",
                "package": "example",
                "aggregate": "zara-plugins",
            },
        }

    def test_required_string_metadata_rejects_surrounding_whitespace(self) -> None:
        for field in (
            "version",
            "api_version",
            "plugin_type",
            "description",
            "path",
            "entrypoint",
            "docs",
            "license",
        ):
            with self.subTest(field=field):
                entry = self.entry()
                entry[field] = f" {entry[field]} "
                with self.assertRaisesRegex(
                    validate_registry.RegistryError,
                    f"{field}.*surrounding whitespace",
                ):
                    validate_registry.validate_entry(entry)

    def test_tags_must_be_nonempty_canonical_strings(self) -> None:
        for tag in ("", "   ", " example", "example "):
            with self.subTest(tag=tag):
                entry = self.entry()
                entry["tags"] = [tag]
                with self.assertRaisesRegex(
                    validate_registry.RegistryError,
                    "tags.*non-empty.*surrounding whitespace",
                ):
                    validate_registry.validate_entry(entry)


if __name__ == "__main__":
    unittest.main()
