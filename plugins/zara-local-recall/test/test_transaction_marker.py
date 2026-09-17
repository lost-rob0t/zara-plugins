"""Regression tests for Local Recall install transaction markers."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import tempfile
import unittest
from pathlib import Path

from local_recall_test_support import LIB_ROOT  # noqa: F401


_tool_path = Path(__file__).resolve().parents[1] / "tools" / "zara-local-recall"
_loader = SourceFileLoader("zara_local_recall_marker_tool", str(_tool_path))
_spec = importlib.util.spec_from_loader("zara_local_recall_marker_tool", _loader)
installer = importlib.util.module_from_spec(_spec)
_loader.exec_module(installer)


class TransactionMarkerTests(unittest.TestCase):
    def _seed(self, home: Path, xdg: Path, marker: str) -> tuple[Path, ...]:
        config_dir = xdg / "zarathushtra" / "plugins" / "zara-local-recall"
        library_dir = config_dir / "lib"
        library_backup = config_dir / ".lib.backup"
        plugin_entry = home / ".zarathushtra" / "plugins" / "zara_local_recall.py"
        wrapper_backup = plugin_entry.with_name(".zara_local_recall.py.backup")
        transaction_marker = config_dir / ".install-transaction.json"
        policy = config_dir / "daemon-policy.json"

        library_dir.mkdir(parents=True)
        (library_dir / "live.txt").write_text("live-library\n", encoding="utf-8")
        library_backup.mkdir()
        (library_backup / "backup.txt").write_text("backup-library\n", encoding="utf-8")
        plugin_entry.parent.mkdir(parents=True)
        plugin_entry.write_text("live-wrapper\n", encoding="utf-8")
        wrapper_backup.write_text("backup-wrapper\n", encoding="utf-8")
        transaction_marker.write_text(marker, encoding="utf-8")
        policy.write_text('{"owner_only": true}\n', encoding="utf-8")
        return (
            library_dir,
            library_backup,
            plugin_entry,
            wrapper_backup,
            transaction_marker,
            policy,
        )

    def _snapshot(self, paths: tuple[Path, ...]) -> tuple[object, ...]:
        values: list[object] = []
        for path in paths:
            if path.is_dir():
                values.append(tuple(sorted((p.relative_to(path).as_posix(), p.read_bytes()) for p in path.rglob("*") if p.is_file())))
            elif path.exists():
                values.append(path.read_bytes())
            else:
                values.append(None)
        return tuple(values)

    def _assert_rejected_without_mutation(self, marker: str) -> None:
        with tempfile.TemporaryDirectory() as home_tmp, tempfile.TemporaryDirectory() as xdg_tmp:
            home = Path(home_tmp)
            xdg = Path(xdg_tmp)
            paths = self._seed(home, xdg, marker)
            before = self._snapshot(paths)

            with self.assertRaisesRegex(ValueError, "invalid install transaction marker"):
                installer.install(home=home, xdg_config_home=xdg)

            self.assertEqual(self._snapshot(paths), before)
            self.assertFalse((paths[0].parent / ".lib.tmp").exists())
            self.assertFalse(paths[2].with_name(".zara_local_recall.py.tmp").exists())

    def test_invalid_json_is_non_destructive(self) -> None:
        self._assert_rejected_without_mutation("{not-json\n")

    def test_missing_key_is_non_destructive(self) -> None:
        self._assert_rejected_without_mutation('{"library_existed": true}\n')

    def test_extra_key_is_non_destructive(self) -> None:
        self._assert_rejected_without_mutation(
            '{"library_existed": true, "wrapper_existed": true, "extra": false}\n'
        )

    def test_non_boolean_value_is_non_destructive(self) -> None:
        self._assert_rejected_without_mutation(
            '{"library_existed": 1, "wrapper_existed": true}\n'
        )


if __name__ == "__main__":
    unittest.main()
