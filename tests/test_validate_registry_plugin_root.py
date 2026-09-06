from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate-registry.py"
SPEC = importlib.util.spec_from_file_location("validate_registry_plugin_root", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validate_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_registry)


class PluginRootConfinementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "repo"
        self.plugins = self.root / "plugins"
        self.plugins.mkdir(parents=True)
        self.original_root = validate_registry.ROOT
        self.original_plugins = validate_registry.PLUGINS_DIR
        validate_registry.ROOT = self.root
        validate_registry.PLUGINS_DIR = self.plugins

    def tearDown(self) -> None:
        validate_registry.ROOT = self.original_root
        validate_registry.PLUGINS_DIR = self.original_plugins
        self.temporary.cleanup()

    def entry(self) -> dict:
        return {
            "name": "zara-example",
            "version": "0.1.0",
            "api_version": "1",
            "plugin_type": "tool",
            "description": "fixture",
            "path": "plugins/zara-example",
            "entrypoint": "entrypoint.py",
            "docs": "plugins/zara-example/README.md",
            "license": "GPL-3.0-or-later",
            "python_dependencies": [],
            "nix": {
                "flake": "github:lost-rob0t/zara-plugins",
                "package": "zara-example",
                "aggregate": "zara-plugins",
            },
            "install": {
                "nix": "nix build github:lost-rob0t/zara-plugins#zara-example",
            },
            "tags": [],
        }

    def test_rejects_plugin_root_symlinked_outside_plugins_directory(self) -> None:
        outside = Path(self.temporary.name) / "outside" / "zara-example"
        outside.mkdir(parents=True)
        (outside / "entrypoint.py").write_text("pass\n", encoding="utf-8")
        (outside / "README.md").write_text("fixture\n", encoding="utf-8")
        (self.plugins / "zara-example").symlink_to(outside, target_is_directory=True)

        with self.assertRaisesRegex(validate_registry.RegistryError, "plugin root"):
            validate_registry.validate_entry(self.entry())


if __name__ == "__main__":
    unittest.main()
