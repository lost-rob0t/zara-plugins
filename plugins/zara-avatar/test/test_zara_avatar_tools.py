"""ZaraAvatarPlugin agent tools: VRM import, listing, and selection.

The plugin exposes LangChain tools so Zara's agent can load an avatar when
the user names a file in chat or voice. langchain_core is optional in CI,
so tool-behavior tests skip when it is unavailable, exactly like the real
Zara integration tests skip without a local Zara checkout.
"""

from __future__ import annotations

import importlib.util
import json
import struct
import tempfile
import threading
import unittest
from pathlib import Path

import avatar_test_support

AVATAR = avatar_test_support.load_avatar_module()

STUB_RENDERER = Path(__file__).parent / "fixtures" / "stub_renderer.py"

_HAS_LANGCHAIN = importlib.util.find_spec("langchain_core") is not None


def _minimal_vrm() -> bytes:
    document = {
        "asset": {"version": "2.0"},
        "extensionsUsed": ["VRMCvrm"],
        "extensions": {"VRMCvrm": {"specVersion": "1.0"}},
    }
    payload = json.dumps(document).encode("utf-8")
    while len(payload) % 4:
        payload += b" "
    header = struct.pack("<4sII", b"glTF", 2, 12 + 8 + len(payload))
    return header + struct.pack("<I", len(payload)) + b"JSON" + payload


@unittest.skipIf(not _HAS_LANGCHAIN, "langchain_core not available")
class AgentToolsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.avatar_dir = Path(self.tmp.name) / "avatars"

    def make_plugin(self, **config_overrides):
        config = {
            "port": 0,
            "avatar_directory": str(self.avatar_dir),
            "renderer_command": [
                "python3",
                "-X",
                "utf8",
                str(STUB_RENDERER),
            ],
            "renderer_startup_timeout": 5.0,
            "renderer_request_timeout": 2.0,
        }
        config.update(config_overrides)
        plugin = AVATAR.create_plugin()
        runtime = avatar_test_support._FakeRuntime(configuration=config)
        plugin.start(runtime)
        self.addCleanup(self.stop_plugin, plugin)
        return plugin, runtime

    def stop_plugin(self, plugin) -> None:
        try:
            plugin.stop()
        except Exception:
            pass

    def tool_map(self, plugin) -> dict:
        from langchain_core.tools import BaseTool

        tools = {tool.name: tool for tool in plugin.tools()}
        for tool in tools.values():
            self.assertIsInstance(tool, BaseTool)
        return tools

    def write_vrm(self, name="Alicia.vrm") -> Path:
        path = Path(self.tmp.name) / name
        path.write_bytes(_minimal_vrm())
        return path

    def test_tool_names(self) -> None:
        plugin, _ = self.make_plugin()
        self.assertEqual(
            sorted(self.tool_map(plugin)),
            ["zara_avatar_import", "zara_avatar_list", "zara_avatar_select"],
        )

    def test_import_tool_imports_selects_and_shows(self) -> None:
        plugin, _ = self.make_plugin()
        source = self.write_vrm()
        result = self.tool_map(plugin)["zara_avatar_import"].invoke(
            {"path": str(source), "name": "Alicia"}
        )
        self.assertIn("imported", result.lower())
        self.assertIn("id", result.lower())
        records = plugin._library.list_avatars()
        self.assertEqual([record.name for record in records], ["Alicia"])
        self.assertIsNotNone(plugin._library.selected())
        status = plugin.status_document()
        self.assertTrue(status["avatar"]["loaded"])
        self.assertEqual(status["avatar"]["visible"], True)

    def test_import_tool_defaults_name_to_file_stem(self) -> None:
        plugin, _ = self.make_plugin()
        source = self.write_vrm("Nova.vrm")
        result = self.tool_map(plugin)["zara_avatar_import"].invoke(
            {"path": str(source)}
        )
        self.assertIn("Nova", result)
        records = plugin._library.list_avatars()
        self.assertEqual([record.name for record in records], ["Nova"])

    def test_import_tool_rejects_missing_file(self) -> None:
        plugin, _ = self.make_plugin()
        missing = Path(self.tmp.name) / "missing.vrm"
        result = self.tool_map(plugin)["zara_avatar_import"].invoke(
            {"path": str(missing)}
        )
        self.assertIn("error", result.lower())

    def test_import_tool_rejects_non_vrm_file(self) -> None:
        plugin, _ = self.make_plugin()
        bad = Path(self.tmp.name) / "garbage.vrm"
        bad.write_bytes(b"not a glb payload" * 8)
        result = self.tool_map(plugin)["zara_avatar_import"].invoke(
            {"path": str(bad)}
        )
        self.assertIn("error", result.lower())
        self.assertIn("vrm", result.lower())

    def test_import_tool_rejects_relative_path(self) -> None:
        plugin, _ = self.make_plugin()
        result = self.tool_map(plugin)["zara_avatar_import"].invoke(
            {"path": "relative/avatar.vrm"}
        )
        self.assertIn("error", result.lower())
        self.assertIn("absolute", result.lower())

    def test_list_tool_reports_avatars_and_selection(self) -> None:
        plugin, _ = self.make_plugin()
        source = self.write_vrm()
        tools = self.tool_map(plugin)
        tools["zara_avatar_import"].invoke({"path": str(source), "name": "Alicia"})
        listing = tools["zara_avatar_list"].invoke({})
        self.assertIn("Alicia", listing)
        self.assertIn("(selected)", listing)

    def test_list_tool_reports_empty_library(self) -> None:
        plugin, _ = self.make_plugin()
        result = self.tool_map(plugin)["zara_avatar_list"].invoke({})
        self.assertIn("no avatars", result.lower())

    def test_select_tool_by_id_and_by_name(self) -> None:
        plugin, _ = self.make_plugin()
        source = self.write_vrm()
        tools = self.tool_map(plugin)
        tools["zara_avatar_import"].invoke({"path": str(source), "name": "Alicia"})
        avatar_id = plugin._library.list_avatars()[0].avatar_id

        by_id = tools["zara_avatar_select"].invoke({"avatar_id": avatar_id})
        self.assertIn("selected", by_id.lower())
        self.assertIn(avatar_id, by_id)

        by_name = tools["zara_avatar_select"].invoke({"name": "ALICIA"})
        self.assertIn("selected", by_name.lower())

    def test_select_tool_unknown_name_points_at_list(self) -> None:
        plugin, _ = self.make_plugin()
        result = self.tool_map(plugin)["zara_avatar_select"].invoke(
            {"name": "nobody"}
        )
        self.assertIn("error", result.lower())
        self.assertIn("list", result.lower())

    def test_select_tool_requires_exactly_one_argument(self) -> None:
        plugin, _ = self.make_plugin()
        tools = self.tool_map(plugin)
        neither = tools["zara_avatar_select"].invoke({})
        both = tools["zara_avatar_select"].invoke(
            {"avatar_id": "a", "name": "b"}
        )
        self.assertIn("error", neither.lower())
        self.assertIn("error", both.lower())

    def test_import_tool_degrades_when_renderer_unavailable(self) -> None:
        plugin, _ = self.make_plugin(
            renderer_command=["false"],
            renderer_startup_timeout=1.0,
        )
        source = self.write_vrm()
        result = self.tool_map(plugin)["zara_avatar_import"].invoke(
            {"path": str(source), "name": "Alicia"}
        )
        self.assertIn("imported", result.lower())
        self.assertIn("could not display", result.lower())
        self.assertIsNone(plugin._library.selected())

    def test_tools_report_plugin_not_running(self) -> None:
        fresh = AVATAR.create_plugin()
        tools = self.tool_map(fresh)
        import_result = tools["zara_avatar_import"].invoke({"path": "/tmp/x.vrm"})
        list_result = tools["zara_avatar_list"].invoke({})
        select_result = tools["zara_avatar_select"].invoke({"name": "x"})
        for result in (import_result, list_result, select_result):
            self.assertIn("not running", result.lower())

    def test_workers_keep_running_during_tool_calls(self) -> None:
        runtime_ref = {}

        plugin, runtime = self.make_plugin()
        runtime_ref["runtime"] = runtime
        source = self.write_vrm()
        self.tool_map(plugin)["zara_avatar_import"].invoke(
            {"path": str(source), "name": "Alicia"}
        )
        for _, worker in runtime.workers:
            self.assertTrue(worker.thread.is_alive())


if __name__ == "__main__":
    unittest.main()
