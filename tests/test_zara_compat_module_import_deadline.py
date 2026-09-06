from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.zara_compat import check_registry


class ZaraCompatibilityModuleImportDeadlineTest(unittest.TestCase):
    @staticmethod
    def _write_fixture(root: Path, names: tuple[str, ...]) -> Path:
        entries = []
        for name in names:
            plugin = root / "plugins" / name
            entrypoint = plugin / "zara-plugin" / "entrypoint.py"
            entrypoint.parent.mkdir(parents=True)
            entrypoint.write_text("pass\n", encoding="utf-8")
            (plugin / "lib").mkdir()
            entries.append(
                {
                    "name": name,
                    "version": "1.0.0",
                    "api_version": "1",
                    "plugin_type": "service",
                    "description": "example",
                    "path": f"plugins/{name}",
                    "entrypoint": "zara-plugin/entrypoint.py",
                }
            )
        (root / "plugins.json").write_text(json.dumps({"plugins": entries}), encoding="utf-8")
        zara_source = root / "zara-source"
        api_root = zara_source / "zara" / "plugins"
        api_root.mkdir(parents=True)
        for filename in ("api.py", "manager.py", "loader.py"):
            (api_root / filename).write_text("pass\n", encoding="utf-8")
        return zara_source

    @staticmethod
    def _contracts(loader):
        class PluginMetadata:
            pass

        class ServicePlugin:
            pass

        return (
            object,
            "1",
            PluginMetadata,
            ServicePlugin,
            lambda paths: (),
            loader,
        )

    def test_blocking_plugin_import_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            zara_source = self._write_fixture(root, ("zara-example",))

            def blocking_loader(path):
                time.sleep(1.0)
                return object()

            started = time.monotonic()
            with patch(
                "scripts.zara_compat._load_runtime_contracts",
                return_value=self._contracts(blocking_loader),
            ):
                failures = check_registry(root, zara_source, call_timeout=0.05)

            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(any("TimeoutError" in failure for failure in failures), failures)

    def test_timeout_aborts_before_loading_later_plugins(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            zara_source = self._write_fixture(root, ("zara-first", "zara-second"))
            calls: list[str] = []

            def loader(path):
                calls.append(Path(path).parents[1].name)
                if calls == ["zara-first"]:
                    time.sleep(1.0)
                return object()

            with patch(
                "scripts.zara_compat._load_runtime_contracts",
                return_value=self._contracts(loader),
            ):
                failures = check_registry(root, zara_source, call_timeout=0.05)

            self.assertEqual(calls, ["zara-first"])
            self.assertEqual(len(failures), 1)
            self.assertIn("zara-first: TimeoutError", failures[0])


if __name__ == "__main__":
    unittest.main()
