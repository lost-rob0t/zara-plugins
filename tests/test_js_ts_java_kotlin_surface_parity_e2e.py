"""Gate JS/TS/Java/Kotlin symbolic conversation state across Desktop/Android semantics."""

from __future__ import annotations

import os
from pathlib import Path

from tests import test_js_ts_java_kotlin_symbolic_conversation_e2e as conversation


CURRENT_DOTFILES = "3309c54ecb5f65c29374de6c60d2135a9ea2f94b"
CURRENT_ZARA_CORE = "29aaaab83ff2ebb27f483c47e43403c1fc252574"


class JsTsJavaKotlinSurfaceParityE2ETests(
    conversation.JsTsJavaKotlinSymbolicConversationE2ETests
):
    @classmethod
    def setUpClass(cls) -> None:
        conversation.CURRENT_DOTFILES = CURRENT_DOTFILES
        conversation.CURRENT_ZARA_CORE = CURRENT_ZARA_CORE
        conversation.composition.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES
        conversation.composition.EXPECTED_ZARA_CORE_COMMIT = CURRENT_ZARA_CORE
        super().setUpClass()
        cls.android_projection_source = (
            cls.zara_core_root
            / "android"
            / "app"
            / "src"
            / "main"
            / "java"
            / "ai"
            / "zara"
            / "app"
            / "history"
            / "SymbolicConversationProjection.kt"
        )
        if not cls.android_projection_source.is_file():
            raise AssertionError(
                f"missing Android projection contract: {cls.android_projection_source}"
            )

    def test_android_projection_tracks_desktop_pure_symbolic_contract(self) -> None:
        for name in conversation._PROVIDER_CREDENTIALS:
            self.assertNotIn(name, os.environ)

        source = self.android_projection_source.read_text(encoding="utf-8")
        required_fragments = (
            "data class SymbolicConversationProjection(",
            'val dialogueStateJson: String = "{}"',
            'val expertEvidenceJson: String = "[]"',
            'val verifiedFactsJson: String = "[]"',
            "val providersEnabled: Boolean = true",
            "val maxModelCalls: Long = 1",
            "val providerCalls: Long = 0",
            "val modelCalls: Long = 0",
            "fun assertPureSymbolic()",
            'check(!providersEnabled)',
            'check(maxModelCalls == 0L)',
            'check(providerCalls == 0L && modelCalls == 0L)',
            'rendererProvenance == SYMBOLIC_RENDERER_ID',
            'PortableJsonValidator.requireObjectArray(projection.expertEvidenceJson, "expertEvidenceJson")',
            '"provider policy widening rejected"',
            '"model-call budget widening rejected"',
            '"project switch must advance projectGeneration"',
            '"desktop_symbolic_projections"',
        )
        for fragment in required_fragments:
            self.assertIn(fragment, source)

        forbidden_fragments = (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "OPENROUTER_API_KEY",
            "fallbackToProvider",
            "fallbackToModel",
        )
        for fragment in forbidden_fragments:
            self.assertNotIn(fragment, source)


if __name__ == "__main__":
    import unittest

    unittest.main()
