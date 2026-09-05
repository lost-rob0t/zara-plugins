from __future__ import annotations

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


if __name__ == "__main__":
    unittest.main()
