from __future__ import annotations

import threading
import time
import unittest
from types import SimpleNamespace

from scripts.zara_compat import CompatibilityError, require_legacy_tool_entrypoint


class LegacyEntrypointCompatibilityTest(unittest.TestCase):
    def test_register_skills_is_exercised_with_zara_loader_signature(self) -> None:
        calls: list[object] = []

        class BaseTool:
            pass

        class Tool(BaseTool):
            name = "legacy.skill"

        def register_skills(prolog_engine):
            calls.append(prolog_engine)
            return [Tool()]

        tools = require_legacy_tool_entrypoint(
            "zara-legacy",
            SimpleNamespace(register_skills=register_skills),
            BaseTool,
            {},
        )

        self.assertEqual(calls, [None])
        self.assertEqual([tool.name for tool in tools], ["legacy.skill"])

    def test_register_skills_rejects_non_base_tool_values(self) -> None:
        class BaseTool:
            pass

        def register_skills(prolog_engine):
            return [SimpleNamespace(name="not-a-tool")]

        with self.assertRaisesRegex(
            CompatibilityError,
            "zara-legacy.*register_skills.*non-BaseTool",
        ):
            require_legacy_tool_entrypoint(
                "zara-legacy",
                SimpleNamespace(register_skills=register_skills),
                BaseTool,
                {},
            )

    def test_noncallable_register_tools_does_not_fall_back_to_register_skills(self) -> None:
        class BaseTool:
            pass

        class Tool(BaseTool):
            name = "legacy.skill"

        def register_skills(prolog_engine):
            return [Tool()]

        with self.assertRaisesRegex(
            CompatibilityError,
            "zara-legacy.*register_tools.*not callable",
        ):
            require_legacy_tool_entrypoint(
                "zara-legacy",
                SimpleNamespace(register_tools=None, register_skills=register_skills),
                BaseTool,
                {},
            )

    def test_blocked_sync_registration_returns_at_deadline(self) -> None:
        release = threading.Event()

        class BaseTool:
            pass

        def register_tools(prolog_engine):
            release.wait(1.0)
            return []

        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                require_legacy_tool_entrypoint(
                    "zara-legacy",
                    SimpleNamespace(register_tools=register_tools),
                    BaseTool,
                    {},
                    timeout=0.01,
                )
        finally:
            release.set()

        self.assertLess(time.monotonic() - started, 0.2)

    def test_completed_registration_propagates_plugin_exception(self) -> None:
        class BaseTool:
            pass

        def register_tools(prolog_engine):
            raise ValueError("broken registration")

        with self.assertRaisesRegex(ValueError, "broken registration"):
            require_legacy_tool_entrypoint(
                "zara-legacy",
                SimpleNamespace(register_tools=register_tools),
                BaseTool,
                {},
                timeout=0.1,
            )


if __name__ == "__main__":
    unittest.main()
