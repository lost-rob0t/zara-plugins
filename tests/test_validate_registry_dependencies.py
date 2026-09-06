from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate-registry.py"
SPEC = importlib.util.spec_from_file_location("validate_registry_dependencies", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validate_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_registry)


class RegistryPythonDependencyMetadataTest(unittest.TestCase):
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

    def test_python_dependencies_require_canonical_unique_strings(self) -> None:
        for dependencies in (
            "langchain-core",
            [None],
            [""],
            [" langchain-core"],
            ["langchain-core "],
            ["langchain-core", "langchain-core"],
        ):
            with self.subTest(dependencies=dependencies):
                entry = self.entry()
                entry["python_dependencies"] = dependencies
                with self.assertRaisesRegex(
                    validate_registry.RegistryError,
                    "python_dependencies.*unique.*canonical",
                ):
                    validate_registry.validate_entry(entry)

    def test_python_dependencies_accept_canonical_unique_strings(self) -> None:
        entry = self.entry()
        entry["python_dependencies"] = ["langchain-core", "pytest"]
        validate_registry.validate_entry(entry)


if __name__ == "__main__":
    unittest.main()
