"""Optional integration test: zara-avatar against the real Zara plugin API.

Discovers a local Zarathushtra checkout through the ZARA_REPO environment
variable or conventional repository locations; never hardcodes a username.
Skips cleanly when Zara is not available locally so the rest of the suite
runs anywhere.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).parents[1]


def _zara_repo_candidates() -> list:
    env = os.environ.get("ZARA_REPO")
    home = Path.home()
    return [
        *( [Path(env).expanduser()] if env else [] ),
        home / "Documents" / "Projects" / "Zarathushtra",
        home / "Documents" / "Projects" / "zarathurshtra",
        home / "git" / "worktrees" / "zarathurshtra-zara-avatar",
    ]


ZARA_ROOT = None
for _candidate in _zara_repo_candidates():
    if (_candidate / "zara" / "plugins" / "api.py").is_file():
        ZARA_ROOT = _candidate
        break


@unittest.skipIf(ZARA_ROOT is None, "Zara source not available locally")
class RealZaraCompatibilityTest(unittest.TestCase):
    """Load zara_avatar.py with the real zara.plugins API."""

    @classmethod
    def setUpClass(cls) -> None:
        root = str(ZARA_ROOT)
        if root not in sys.path:
            sys.path.insert(0, root)
        try:
            import zara.plugins.api  # noqa: F401
        except ImportError as error:
            raise unittest.SkipTest(
                f"Zara dependencies unavailable ({error}); skipping integration"
            ) from error

    def _configuration(self, avatar_directory: str) -> dict:
        return {
            "port": 0,
            "avatar_directory": avatar_directory,
            "renderer_command": [
                sys.executable,
                "-X",
                "utf8",
                str(REPO / "test" / "fixtures" / "stub_renderer.py"),
            ],
        }

    def test_service_plugin_contract(self) -> None:
        from zara.plugins import PluginMetadata, ServicePlugin
        from zara.plugins.api import PLUGIN_API_VERSION
        from zara.plugins.loader import load_plugin_module

        module = load_plugin_module(REPO / "zara-plugin" / "zara_avatar.py")
        plugin = module.create_plugin()
        self.assertIsInstance(plugin.metadata, PluginMetadata)
        self.assertIsInstance(plugin, ServicePlugin)
        self.assertEqual(plugin.metadata.name, "zara-avatar")
        self.assertEqual(plugin.metadata.api_version, PLUGIN_API_VERSION)

    def test_real_plugin_manager_lifecycle(self) -> None:
        from zara.plugins.manager import PluginManager, PluginState
        from zara.runtime import bridge

        def configuration_provider(name):
            return {
                "port": 0,
                "avatar_directory": str(Path(self.tmp.name) / "avatars"),
                "renderer_command": [
                    sys.executable,
                    "-X",
                    "utf8",
                    str(REPO / "test" / "fixtures" / "stub_renderer.py"),
                ],
            }

        def dispatcher(command):
            future: concurrent.futures.Future = concurrent.futures.Future()
            future.set_result(None)
            return future

        def subscriber(*, maxsize):
            return bridge.subscribe(maxsize=maxsize)

        with tempfile.TemporaryDirectory() as tmp:
            manager = PluginManager(
                [REPO / "zara-plugin"],
                configuration_provider=lambda name: {
                    "port": 0,
                    "avatar_directory": str(Path(tmp) / "avatars"),
                    "renderer_command": [
                        sys.executable,
                        "-X",
                        "utf8",
                        str(REPO / "test" / "fixtures" / "stub_renderer.py"),
                    ],
                },
                status_provider=lambda: type(
                    "_Status",
                    (),
                    {"state": "running", "alive": True, "thread_id": 1},
                )(),
                dispatcher=dispatcher,
                subscriber=subscriber,
                tool_registrar=lambda tools: None,
                tool_unregistrar=lambda names: None,
                publisher=lambda event: None,
                lifecycle_timeout=10.0,
            )

            async def lifecycle() -> None:
                await manager.start()
                diagnostics = {
                    diagnostic.name: diagnostic
                    for diagnostic in manager.diagnostics()
                }
                self.assertIn("zara-avatar", diagnostics)
                state = diagnostics["zara-avatar"]
                self.assertEqual(state.state, PluginState.RUNNING, state.error)
                await manager.stop()
                diagnostics = {
                    diagnostic.name: diagnostic
                    for diagnostic in manager.diagnostics()
                }
                self.assertEqual(diagnostics["zara-avatar"].state, PluginState.STOPPED)

            asyncio.run(asyncio.wait_for(lifecycle(), timeout=30))


if __name__ == "__main__":
    unittest.main()
