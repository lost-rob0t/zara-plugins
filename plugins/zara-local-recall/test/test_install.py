"""Deterministic tests for the installer layout."""

import os
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
    def _paths(self, home: Path, xdg: Path) -> tuple[Path, Path, Path, Path, Path]:
        config_dir = xdg / "zarathushtra" / "plugins" / "zara-local-recall"
        library_dir = config_dir / "lib"
        plugin_entry = home / ".zarathushtra" / "plugins" / "zara_local_recall.py"
        library_backup = config_dir / ".lib.backup"
        wrapper_backup = plugin_entry.with_name(".zara_local_recall.py.backup")
        return config_dir, library_dir, plugin_entry, library_backup, wrapper_backup

    def _seed_old_install(self, home: Path, xdg: Path) -> tuple[Path, Path, Path, Path, Path]:
        config_dir, library_dir, plugin_entry, library_backup, wrapper_backup = self._paths(home, xdg)
        library_dir.mkdir(parents=True)
        (library_dir / "old-marker.txt").write_text("old-library\n", encoding="utf-8")
        plugin_entry.parent.mkdir(parents=True)
        plugin_entry.write_text("old-wrapper\n", encoding="utf-8")
        (config_dir / "daemon-policy.json").write_text('{"owner_only": true}\n', encoding="utf-8")
        return config_dir, library_dir, plugin_entry, library_backup, wrapper_backup

    def _assert_old_install_intact(self, home: Path, xdg: Path) -> None:
        config_dir, library_dir, plugin_entry, library_backup, wrapper_backup = self._paths(home, xdg)
        self.assertEqual((library_dir / "old-marker.txt").read_text(encoding="utf-8"), "old-library\n")
        self.assertEqual(plugin_entry.read_text(encoding="utf-8"), "old-wrapper\n")
        self.assertEqual(
            (config_dir / "daemon-policy.json").read_text(encoding="utf-8"),
            '{"owner_only": true}\n',
        )
        self.assertFalse((config_dir / ".lib.tmp").exists())
        self.assertFalse(plugin_entry.with_name(".zara_local_recall.py.tmp").exists())
        self.assertFalse(library_backup.exists())
        self.assertFalse(wrapper_backup.exists())
        self.assertFalse((config_dir / ".install-transaction.json").exists())

    def _fail_next_library_publish(self, library_dir: Path):
        original_replace = os.replace

        def fail(source: str | Path, destination: str | Path) -> None:
            if Path(destination) == library_dir and Path(source).name == ".lib.tmp":
                raise OSError("injected library publication failure")
            original_replace(source, destination)

        return mock.patch.object(installer.os, "replace", side_effect=fail)

    def _fail_next_wrapper_publish(self, plugin_entry: Path):
        original_replace = os.replace

        def fail(source: str | Path, destination: str | Path) -> None:
            if Path(destination) == plugin_entry and Path(source).name == ".zara_local_recall.py.tmp":
                raise OSError("injected wrapper publication failure")
            original_replace(source, destination)

        return mock.patch.object(installer.os, "replace", side_effect=fail)

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

            with self._fail_next_library_publish(library_dir):
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

            with self._fail_next_wrapper_publish(plugin_entry):
                with self.assertRaisesRegex(OSError, "injected wrapper publication failure"):
                    installer.install(home=home, xdg_config_home=xdg)

            self.assertEqual(plugin_entry.read_bytes(), old_plugin)
            self.assertEqual(sentinel.read_text(encoding="utf-8"), "known-good\n")
            self.assertEqual(config_state.read_text(encoding="utf-8"), '{"owner_only": true}\n')
            self.assertFalse((library_dir.parent / ".lib.tmp").exists())
            self.assertFalse((library_dir.parent / ".lib.backup").exists())
            self.assertFalse(plugin_entry.with_name(".zara_local_recall.py.backup").exists())

    def test_recovers_process_death_after_library_backup(self) -> None:
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as xdg_tmp:
            home = Path(home_tmp)
            xdg = Path(xdg_tmp)
            config_dir, library_dir, _plugin_entry, library_backup, _ = self._seed_old_install(home, xdg)
            (config_dir / ".install-transaction.json").write_text(
                '{"library_existed": true, "wrapper_existed": true}\n', encoding="utf-8"
            )
            os.replace(library_dir, library_backup)

            with self._fail_next_library_publish(library_dir):
                with self.assertRaisesRegex(OSError, "library publication failure"):
                    installer.install(home=home, xdg_config_home=xdg)

            self._assert_old_install_intact(home, xdg)

    def test_recovers_process_death_after_library_publication(self) -> None:
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as xdg_tmp:
            home = Path(home_tmp)
            xdg = Path(xdg_tmp)
            config_dir, library_dir, _plugin_entry, library_backup, _ = self._seed_old_install(home, xdg)
            (config_dir / ".install-transaction.json").write_text(
                '{"library_existed": true, "wrapper_existed": true}\n', encoding="utf-8"
            )
            os.replace(library_dir, library_backup)
            library_dir.mkdir()
            (library_dir / "new-marker.txt").write_text("new-library\n", encoding="utf-8")

            with self._fail_next_library_publish(library_dir):
                with self.assertRaisesRegex(OSError, "library publication failure"):
                    installer.install(home=home, xdg_config_home=xdg)

            self._assert_old_install_intact(home, xdg)

    def test_recovers_process_death_after_wrapper_publication_before_commit(self) -> None:
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as xdg_tmp:
            home = Path(home_tmp)
            xdg = Path(xdg_tmp)
            config_dir, library_dir, plugin_entry, library_backup, wrapper_backup = self._seed_old_install(home, xdg)
            (config_dir / ".install-transaction.json").write_text(
                '{"library_existed": true, "wrapper_existed": true}\n', encoding="utf-8"
            )
            os.replace(library_dir, library_backup)
            library_dir.mkdir()
            (library_dir / "new-marker.txt").write_text("new-library\n", encoding="utf-8")
            os.replace(plugin_entry, wrapper_backup)
            plugin_entry.write_text("new-wrapper\n", encoding="utf-8")

            with self._fail_next_library_publish(library_dir):
                with self.assertRaisesRegex(OSError, "library publication failure"):
                    installer.install(home=home, xdg_config_home=xdg)

            self._assert_old_install_intact(home, xdg)

    def test_post_commit_cleanup_residue_does_not_clobber_live_generation(self) -> None:
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as xdg_tmp:
            home = Path(home_tmp)
            xdg = Path(xdg_tmp)
            config_dir, library_dir, plugin_entry, library_backup, wrapper_backup = self._paths(home, xdg)
            library_dir.mkdir(parents=True)
            (library_dir / "new-marker.txt").write_text("new-library\n", encoding="utf-8")
            plugin_entry.parent.mkdir(parents=True)
            plugin_entry.write_text("new-wrapper\n", encoding="utf-8")
            library_backup.mkdir()
            (library_backup / "old-marker.txt").write_text("old-library\n", encoding="utf-8")
            wrapper_backup.write_text("old-wrapper\n", encoding="utf-8")
            (config_dir / "daemon-policy.json").write_text('{"owner_only": true}\n', encoding="utf-8")

            with self._fail_next_library_publish(library_dir):
                with self.assertRaisesRegex(OSError, "library publication failure"):
                    installer.install(home=home, xdg_config_home=xdg)

            self.assertTrue((library_dir / "new-marker.txt").exists())
            self.assertFalse((library_dir / "old-marker.txt").exists())
            self.assertEqual(plugin_entry.read_text(encoding="utf-8"), "new-wrapper\n")
            self.assertFalse(library_backup.exists())
            self.assertFalse(wrapper_backup.exists())
            self.assertEqual(
                (config_dir / "daemon-policy.json").read_text(encoding="utf-8"),
                '{"owner_only": true}\n',
            )


if __name__ == "__main__":
    unittest.main()
