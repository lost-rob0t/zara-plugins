from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.zara_compat import check_registry


class ZaraCompatibilityDependencyEnvironmentTest(unittest.TestCase):
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

    def test_live_optional_secret_is_hidden_before_module_load_and_restored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "registry"
            zara = Path(directory) / "zara-source"
            entrypoint = root / "plugins" / "zara-discord" / "zara-plugin" / "entrypoint.py"
            entrypoint.parent.mkdir(parents=True)
            (root / "plugins" / "zara-discord" / "lib").mkdir()
            entrypoint.write_text(
                "import os\n"
                "if os.environ.get('ZARA_DISCORD_TOKEN') is not None:\n"
                "    raise RuntimeError('live optional dependency leaked into plugin import')\n"
                "from zara.plugins import PluginMetadata, ServicePlugin\n"
                "class Plugin(ServicePlugin):\n"
                "    metadata = PluginMetadata('zara-discord', '0.3.0', '1', 'service', 'Discord test plugin')\n"
                "    def tools(self): return ()\n"
                "    def start(self, runtime): pass\n"
                "    def stop(self): pass\n"
                "def create_plugin(): return Plugin()\n",
                encoding="utf-8",
            )
            (root / "plugins.json").write_text(
                json.dumps(
                    {
                        "plugins": [
                            {
                                "name": "zara-discord",
                                "version": "0.3.0",
                                "api_version": "1",
                                "plugin_type": "service",
                                "description": "Discord test plugin",
                                "path": "plugins/zara-discord",
                                "entrypoint": "zara-plugin/entrypoint.py",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )

            package = zara / "zara" / "plugins"
            package.mkdir(parents=True)
            (zara / "zara" / "__init__.py").write_text("", encoding="utf-8")
            (package / "__init__.py").write_text(
                "PLUGIN_API_VERSION='1'\n"
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
                "    spec=importlib.util.spec_from_file_location('compat_dependency_fixture', path)\n"
                "    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); return module\n"
                "def iter_plugin_files(paths):\n"
                "    for root in paths:\n"
                "        yield from Path(root).glob('*.py')\n",
                encoding="utf-8",
            )
            langchain = zara / "langchain_core"
            langchain.mkdir()
            (langchain / "__init__.py").write_text("", encoding="utf-8")
            (langchain / "tools.py").write_text("class BaseTool: pass\n", encoding="utf-8")

            previous = os.environ.get("ZARA_DISCORD_TOKEN")
            os.environ["ZARA_DISCORD_TOKEN"] = "live-secret"
            try:
                with patch(
                    "scripts.zara_compat._load_runtime_contracts",
                    return_value=self._parent_contracts(),
                ):
                    self.assertEqual(check_registry(root, zara), [])
                self.assertEqual(os.environ.get("ZARA_DISCORD_TOKEN"), "live-secret")
            finally:
                if previous is None:
                    os.environ.pop("ZARA_DISCORD_TOKEN", None)
                else:
                    os.environ["ZARA_DISCORD_TOKEN"] = previous


if __name__ == "__main__":
    unittest.main()
