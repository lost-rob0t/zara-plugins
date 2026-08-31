"""Expression policy tests: emotion mapping and graceful fallback (red-first)."""

from __future__ import annotations

import unittest

import avatar_test_support

AVATAR = avatar_test_support.load_avatar_module()


class EmotionMappingTest(unittest.TestCase):
    def test_every_emotion_maps_to_an_expression(self) -> None:
        for emotion in AVATAR.EMOTIONS:
            expression = AVATAR.expression_for_emotion(emotion)
            self.assertIn(expression, AVATAR.EXPRESSIONS)

    def test_direct_emotion_mapping(self) -> None:
        expected = {
            "neutral": "neutral",
            "happy": "happy",
            "sad": "sad",
            "annoyed": "annoyed",
            "excited": "excited",
            "embarrassed": "embarrassed",
        }
        for emotion, expression in expected.items():
            self.assertEqual(AVATAR.expression_for_emotion(emotion), expression)

    def test_unknown_emotion_falls_back_to_neutral(self) -> None:
        self.assertEqual(AVATAR.expression_for_emotion("smug"), "neutral")


class ExpressionFallbackTest(unittest.TestCase):
    def test_native_expression_used_when_available(self) -> None:
        resolved = AVATAR.resolve_expression("embarrassed", {"embarrassed", "happy"})
        self.assertEqual(resolved, "embarrassed")

    def test_embarrassed_fallback_chain(self) -> None:
        self.assertEqual(AVATAR.resolve_expression("embarrassed", set()), "neutral")
        self.assertEqual(AVATAR.resolve_expression("embarrassed", {"happy"}), "happy")

    def test_angry_falls_back_to_annoyed_then_neutral(self) -> None:
        self.assertEqual(AVATAR.resolve_expression("angry", {"annoyed"}), "annoyed")
        self.assertEqual(AVATAR.resolve_expression("angry", set()), "neutral")

    def test_neutral_always_resolves(self) -> None:
        self.assertEqual(AVATAR.resolve_expression("neutral", set()), "neutral")

    def test_every_chain_ends_at_neutral(self) -> None:
        for expression in AVATAR.EXPRESSIONS:
            resolved = AVATAR.resolve_expression(expression, set())
            self.assertEqual(resolved, "neutral")

    def test_fallback_prefers_earlier_chain_entries(self) -> None:
        resolved = AVATAR.resolve_expression("surprised", {"surprised", "happy"})
        self.assertEqual(resolved, "surprised")

    def test_unknown_expression_falls_back_to_neutral(self) -> None:
        self.assertEqual(AVATAR.resolve_expression("wink", {"happy"}), "neutral")

    def test_missing_morphs_never_crash(self) -> None:
        for expression in AVATAR.EXPRESSIONS:
            resolved = AVATAR.resolve_expression(expression, frozenset())
            self.assertIn(resolved, AVATAR.EXPRESSIONS)


if __name__ == "__main__":
    unittest.main()
