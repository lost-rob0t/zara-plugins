"""Deterministic tests for the installer layout."""

import tempfile
import unittest
from pathlib import Path

from local_recall_test_support import LIB_ROOT  # noqa: F401

import importlib.util
from importlib.machinery import SourceFileLoader

_tool_path = Path(__file__).resolve().parents[1] / "tools" / "zara-local-recall"
_loader = SourceFileLoader("zara_local_recall_tool", str(_tool_path))
_spec = importlib.util.spec_from_loader("zara_local_recall_tool", _loader)
installer = importlib.util.module_from_spec(_spec)
_loader.exec_module(installer)


class InstallerTests(unittest.TestCase):
    def test_install_places_entry_and_library(self) -> None:
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as xdg_tmp:
            home = Path(home_tmp)
            xdg = Path(xdg_tmp)
            plugin_entry, library_dir = installer.install(home=home, xdg_config_home=xdg)
            self.assertEqual(plugin_entry, home / ".zarathushtra" / "plugins" / "zara_local_recall.py")
            self.assertTrue(plugin_entry.is_file())
            self.assertEqual(
                library_dir,
                xdg / "zarathushtra" / "plugins" / "zara-local-recall" / "lib",
            )
            self.assertTrue((library_dir / "zara_local_recall_service" / "plugin.py").is_file())
            self.assertFalse((library_dir / "zara_local_recall_service" / "__pycache__").exists())

    def test_install_is_idempotent_and_preserves_staging_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as xdg_tmp:
            home = Path(home_tmp)
            xdg = Path(xdg_tmp)
            installer.install(home=home, xdg_config_home=xdg)
            plugin_entry, library_dir = installer.install(home=home, xdg_config_home=xdg)
            self.assertTrue(plugin_entry.is_file())
            self.assertFalse((library_dir.parent / ".lib.tmp").exists())


if __name__ == "__main__":
    unittest.main()
