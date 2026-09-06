from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.zara_compat import check_registry


class ZaraCompatibilityModuleImportDeadlineTest(unittest.TestCase):
    def test_blocking_plugin_import_is_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plugin = root / "plugins" / "zara-example"
            entrypoint = plugin / "zara-plugin" / "example.py"
            entrypoint.parent.mkdir(parents=True)
            entrypoint.write_text("pass\n", encoding="utf-8")
            (plugin / "lib").mkdir()
            (root / "plugins.json").write_text(
                json.dumps(
                    {
                        "plugins": [
                            {
                                "name": "zara-example",
                                "version": "1.0.0",
                                "api_version": "1",
                                "plugin_type": "service",
                                "description": "example",
                                "path": "plugins/zara-example",
                                "entrypoint": "zara-plugin/example.py",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            zara_source = root / "zara-source"
            api_root = zara_source / "zara" / "plugins"
            api_root.mkdir(parents=True)
            for name in ("api.py", "manager.py", "loader.py"):
                (api_root / name).write_text("pass\n", encoding="utf-8")

            class PluginMetadata:
                pass

            class ServicePlugin:
                pass

            def blocking_loader(path):
                time.sleep(1.0)
                return object()

            contracts = (
                object,
                "1",
                PluginMetadata,
                ServicePlugin,
                lambda paths: (),
                blocking_loader,
            )
            started = time.monotonic()
            with patch("scripts.zara_compat._load_runtime_contracts", return_value=contracts):
                failures = check_registry(root, zara_source, call_timeout=0.05)

            self.assertLess(time.monotonic() - started, 0.5)
            self.assertTrue(any("TimeoutError" in failure for failure in failures), failures)


if __name__ == "__main__":
    unittest.main()
