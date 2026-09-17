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
        for index, name in enumerate(names):
            plugin = root / "plugins" / name
            entrypoint = plugin / "zara-plugin" / "entrypoint.py"
            entrypoint.parent.mkdir(parents=True)
            (plugin / "lib").mkdir()
            delay = "import time; time.sleep(30)\n" if index == 0 else ""
            entrypoint.write_text(
                delay
                + "from zara.plugins import PluginMetadata, ServicePlugin\n"
                + "class Plugin(ServicePlugin):\n"
                + f"    metadata = PluginMetadata({name!r}, '1.0.0', '1', 'service', 'example')\n"
                + "    def tools(self): return ()\n"
                + "    def start(self, runtime): pass\n"
                + "    def stop(self): pass\n"
                + "def create_plugin(): return Plugin()\n",
                encoding="utf-8",
            )
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
        package = zara_source / "zara" / "plugins"
        package.mkdir(parents=True)
        (zara_source / "zara" / "__init__.py").write_text("", encoding="utf-8")
        (package / "__init__.py").write_text(
            "PLUGIN_API_VERSION = '1'\n"
            "class PluginMetadata:\n"
            "    def __init__(self, name, version, api_version, plugin_type, description):\n"
            "        self.name=name; self.version=version; self.api_version=api_version\n"
            "        self.plugin_type=plugin_type; self.description=description\n"
            "class ServicePlugin: pass\n",
            encoding="utf-8",
        )
        (package / "api.py").write_text("pass\n", encoding="utf-8")
        (package / "manager.py").write_text("pass\n", encoding="utf-8")
        (package / "loader.py").write_text(
            "import importlib.util\nfrom pathlib import Path\n"
            "def load_plugin_module(path):\n"
            "    spec=importlib.util.spec_from_file_location('compat_fixture_plugin', path)\n"
            "    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module\n"
            "def iter_plugin_files(paths):\n"
            "    for root in paths:\n"
            "        yield from Path(root).glob('*.py')\n",
            encoding="utf-8",
        )
        return zara_source

    @staticmethod
    def _parent_contracts():
        return (
            object,
            "1",
            object,
            object,
            lambda paths: tuple(path for root in paths for path in Path(root).glob("*.py")),
            None,
        )

    def test_blocking_plugin_import_is_bounded_by_child_process(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            zara_source = self._write_fixture(root, ("zara-example",))

            started = time.monotonic()
            with patch(
                "scripts.zara_compat._load_runtime_contracts",
                return_value=self._parent_contracts(),
            ):
                failures = check_registry(root, zara_source, call_timeout=0.05)

            self.assertLess(time.monotonic() - started, 2.0)
            self.assertTrue(any("TimeoutError" in failure for failure in failures), failures)

    def test_timeout_does_not_prevent_later_plugin_validation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            zara_source = self._write_fixture(root, ("zara-first", "zara-second"))

            with patch(
                "scripts.zara_compat._load_runtime_contracts",
                return_value=self._parent_contracts(),
            ):
                failures = check_registry(root, zara_source, call_timeout=0.05)

            self.assertEqual(len(failures), 1, failures)
            self.assertIn("zara-first: TimeoutError", failures[0])


if __name__ == "__main__":
    unittest.main()
