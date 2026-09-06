from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.zara_compat import check_registry


class FakeBaseTool:
    pass


class FakeMetadata:
    def __init__(self) -> None:
        self.name = "zara-discord"
        self.version = "0.3.0"
        self.api_version = "1"
        self.plugin_type = "service"
        self.description = "Discord test plugin"


class FakeServicePlugin:
    metadata = FakeMetadata()

    def tools(self):
        return ()

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None


class ZaraCompatibilityDependencyEnvironmentTest(unittest.TestCase):
    def test_live_optional_secret_is_hidden_before_module_load_and_restored(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "registry"
            zara = Path(directory) / "zara"
            entrypoint = root / "plugins" / "zara-discord" / "zara-plugin" / "entrypoint.py"
            entrypoint.parent.mkdir(parents=True)
            entrypoint.write_text("pass\n", encoding="utf-8")
            (zara / "zara" / "plugins").mkdir(parents=True)
            for name in ("api.py", "manager.py", "loader.py"):
                (zara / "zara" / "plugins" / name).write_text("pass\n", encoding="utf-8")
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

            def load_plugin_module(path: Path):
                if os.environ.get("ZARA_DISCORD_TOKEN") is not None:
                    raise RuntimeError("live optional dependency leaked into plugin import")
                return SimpleNamespace(create_plugin=FakeServicePlugin)

            def iter_plugin_files(paths):
                return tuple(Path(paths[0]).glob("*.py"))

            contracts = (
                FakeBaseTool,
                "1",
                FakeMetadata,
                FakeServicePlugin,
                iter_plugin_files,
                load_plugin_module,
            )
            previous = os.environ.get("ZARA_DISCORD_TOKEN")
            os.environ["ZARA_DISCORD_TOKEN"] = "live-secret"
            try:
                with patch("scripts.zara_compat._load_runtime_contracts", return_value=contracts):
                    self.assertEqual(check_registry(root, zara), [])
                self.assertEqual(os.environ.get("ZARA_DISCORD_TOKEN"), "live-secret")
            finally:
                if previous is None:
                    os.environ.pop("ZARA_DISCORD_TOKEN", None)
                else:
                    os.environ["ZARA_DISCORD_TOKEN"] = previous


if __name__ == "__main__":
    unittest.main()
