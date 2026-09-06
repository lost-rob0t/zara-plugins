from __future__ import annotations

import json
import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str = ""
    api_version: str = "1"
    description: str = ""


class ServicePlugin:
    pass


zara = types.ModuleType("zara")
zara_plugins = types.ModuleType("zara.plugins")
zara_plugins.PluginMetadata = PluginMetadata
zara_plugins.ServicePlugin = ServicePlugin
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", zara_plugins)

from zara_coding.task_plugin import TaskStateCodingPlugin


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration


class TaskPluginTest(unittest.TestCase):
    def test_task_tools_are_part_of_service_surface(self) -> None:
        tools = {tool.name for tool in TaskStateCodingPlugin().tools()}
        self.assertTrue(
            {
                "coding.task.create",
                "coding.task.get",
                "coding.task.record-evidence",
                "coding.task.complete",
            }.issubset(tools)
        )

    def test_public_tool_cannot_self_author_passing_evidence(self) -> None:
        class Session:
            def record_evidence(self, *args, **kwargs):
                self.fail("untrusted passing evidence reached task state")

        plugin = TaskStateCodingPlugin()
        plugin.task_state = Session()

        with self.assertRaisesRegex(ValueError, "verifier-owned"):
            plugin.task_record_evidence("task-1", "tests", "passed", "looks good")

    def test_public_tool_can_record_failed_observation(self) -> None:
        calls = []

        class Session:
            def record_evidence(self, task_id, **kwargs):
                calls.append((task_id, kwargs))
                return {"status": "ok"}

        plugin = TaskStateCodingPlugin()
        plugin.task_state = Session()

        result = json.loads(
            plugin.task_record_evidence("task-1", "tests", "failed", "1 failed")
        )

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(
            calls,
            [("task-1", {"kind": "tests", "status": "failed", "detail": "1 failed"})],
        )

    def test_task_creation_binds_fresh_repository_identity(self) -> None:
        calls: list[Path] = []

        class Inspector:
            def inspect(self, path: Path):
                calls.append(path)
                return {
                    "root": "/projects/demo",
                    "head": "a" * 40,
                    "branch": "main",
                    "dirty": False,
                    "changed_paths": [],
                }

        class Session:
            def create_task(self, task_id, **kwargs):
                return {"status": "ok", "task": {"id": task_id, **kwargs}}

        plugin = TaskStateCodingPlugin()
        plugin.inspector = Inspector()
        plugin.task_state = Session()

        result = json.loads(
            plugin.task_create(
                "task-1",
                "fix regression",
                repository_path="/projects/demo/src/module.py",
                completion_criteria=["tests-pass"],
            )
        )

        self.assertEqual(calls, [Path("/projects/demo/src/module.py")])
        self.assertEqual(
            result["task"]["repository"],
            {"root": "/projects/demo", "head": "a" * 40, "branch": "main"},
        )

    def test_missing_prolog_configuration_degrades_without_breaking_startup(self) -> None:
        plugin = TaskStateCodingPlugin()
        plugin.start(Runtime({"plugins": {"zara-coding": {}}}))

        status = json.loads(plugin.status())

        self.assertEqual(
            status["task_state"],
            {"status": "unavailable", "reason": "prolog-rlm-checkout-not-configured"},
        )
        with self.assertRaisesRegex(RuntimeError, "prolog-rlm-checkout-not-configured"):
            plugin.task_get("task-1")

    def test_stop_clears_task_state_before_base_service_shutdown(self) -> None:
        class Session:
            stopped = False

            def stop(self):
                self.stopped = True

        plugin = TaskStateCodingPlugin()
        session = Session()
        plugin.task_state = session

        plugin.stop()

        self.assertTrue(session.stopped)
        self.assertIsNone(plugin.task_state)
        self.assertEqual(plugin.task_state_reason, "stopped")


if __name__ == "__main__":
    unittest.main()
