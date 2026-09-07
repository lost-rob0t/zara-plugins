"""Deterministic tests for the installer layout."""

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    def test_failed_library_publication_preserves_previous_install(self) -> None:
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as xdg_tmp:
            home = Path(home_tmp)
            xdg = Path(xdg_tmp)
            plugin_entry, library_dir = installer.install(home=home, xdg_config_home=xdg)
            old_plugin = plugin_entry.read_bytes()
            sentinel = library_dir / "previous-generation.txt"
            sentinel.write_text("known-good\n", encoding="utf-8")
            config_state = library_dir.parent / "daemon-policy.json"
            config_state.write_text('{"owner_only": true}\n', encoding="utf-8")

            original_rename = Path.rename

            def fail_library_publish(path: Path, target: Path) -> Path:
                if path.name == ".lib.tmp" and Path(target) == library_dir:
                    raise OSError("injected library publication failure")
                return original_rename(path, target)

            with mock.patch.object(Path, "rename", autospec=True, side_effect=fail_library_publish):
                with self.assertRaisesRegex(OSError, "injected library publication failure"):
                    installer.install(home=home, xdg_config_home=xdg)

            self.assertEqual(plugin_entry.read_bytes(), old_plugin)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "known-good\n")
            self.assertEqual(config_state.read_text(encoding="utf-8"), '{"owner_only": true}\n')
            self.assertFalse((library_dir.parent / ".lib.tmp").exists())
            self.assertFalse((library_dir.parent / ".lib.backup").exists())

    def test_failed_wrapper_publication_preserves_previous_install(self) -> None:
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as xdg_tmp:
            home = Path(home_tmp)
            xdg = Path(xdg_tmp)
            plugin_entry, library_dir = installer.install(home=home, xdg_config_home=xdg)
            old_plugin = plugin_entry.read_bytes()
            sentinel = library_dir / "previous-generation.txt"
            sentinel.write_text("known-good\n", encoding="utf-8")
            config_state = library_dir.parent / "daemon-policy.json"
            config_state.write_text('{"owner_only": true}\n', encoding="utf-8")
            original_copyfile = shutil.copyfile

            def fail_wrapper_publish(src: str | Path, dst: str | Path, *args: object, **kwargs: object) -> str:
                if Path(dst) == plugin_entry:
                    raise OSError("injected wrapper publication failure")
                return original_copyfile(src, dst, *args, **kwargs)

            with mock.patch.object(installer.shutil, "copyfile", side_effect=fail_wrapper_publish):
                with self.assertRaisesRegex(OSError, "injected wrapper publication failure"):
                    installer.install(home=home, xdg_config_home=xdg)

            self.assertEqual(plugin_entry.read_bytes(), old_plugin)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "known-good\n")
            self.assertEqual(config_state.read_text(encoding="utf-8"), '{"owner_only": true}\n')
            self.assertFalse((library_dir.parent / ".lib.tmp").exists())
            self.assertFalse((library_dir.parent / ".lib.backup").exists())
            self.assertFalse(plugin_entry.with_name(".zara_local_recall.py.backup").exists())


if __name__ == "__main__":
    unittest.main()
