"""Protocol tests for Zara's avatar plugin (red-first)."""

from __future__ import annotations

import dataclasses
import unittest

import avatar_test_support


AVATAR = avatar_test_support.load_avatar_module()


class VocabularyTest(unittest.TestCase):
    def test_presence_vocabulary(self) -> None:
        self.assertEqual(
            AVATAR.PRESENCES, ("idle", "listening", "thinking", "speaking")
        )

    def test_emotion_vocabulary(self) -> None:
        self.assertEqual(
            AVATAR.EMOTIONS,
            ("neutral", "happy", "sad", "annoyed", "excited", "embarrassed"),
        )

    def test_expression_vocabulary(self) -> None:
        self.assertEqual(
            AVATAR.EXPRESSIONS,
            (
                "neutral",
                "happy",
                "sad",
                "angry",
                "annoyed",
                "relaxed",
                "surprised",
                "excited",
                "embarrassed",
            ),
        )

    def test_gesture_vocabulary(self) -> None:
        self.assertEqual(
            AVATAR.GESTURES, ("wave", "nod", "shrug", "point")
        )

    def test_framing_vocabulary(self) -> None:
        self.assertEqual(AVATAR.FRAMINGS, ("half", "full"))

    def test_semantic_animation_vocabulary(self) -> None:
        self.assertEqual(
            AVATAR.SEMANTIC_ANIMATIONS,
            (
                "idle",
                "thinking",
                "wave",
                "nod",
                "shrug",
                "point",
                "happy",
                "sad",
                "annoyed",
                "excited",
            ),
        )

    def test_viseme_vocabulary(self) -> None:
        self.assertEqual(AVATAR.VISEMES, ("a", "i", "u", "e", "o"))


class AvatarStateTest(unittest.TestCase):
    def test_defaults(self) -> None:
        state = AVATAR.AvatarState()
        self.assertFalse(state.loaded)
        self.assertFalse(state.visible)
        self.assertIsNone(state.avatar_id)
        self.assertEqual(state.presence, "idle")
        self.assertEqual(state.emotion, "neutral")
        self.assertEqual(state.expression, "neutral")
        self.assertIsNone(state.animation)
        self.assertFalse(state.animation_loop)
        self.assertEqual(state.animation_speed, 1.0)
        self.assertEqual(state.gaze_target, "auto")
        self.assertFalse(state.speaking)
        self.assertFalse(state.lipsync_active)
        self.assertEqual(state.position, (0.0, 0.0, 0.0))
        self.assertEqual(state.rotation, (0.0, 0.0, 0.0))
        self.assertEqual(state.scale, 1.0)
        self.assertEqual(state.framing, "half")

    def test_state_is_immutable(self) -> None:
        state = AVATAR.AvatarState()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            state.presence = "thinking"  # type: ignore[misc]

    def test_document_uses_camel_case(self) -> None:
        document = AVATAR.AvatarState(
            loaded=True,
            visible=True,
            avatar_id="a-1",
            presence="thinking",
        ).to_document()
        self.assertTrue(document["loaded"])
        self.assertTrue(document["visible"])
        self.assertEqual(document["avatarId"], "a-1")
        self.assertEqual(document["presence"], "thinking")
        self.assertEqual(document["animationSpeed"], 1.0)
        self.assertEqual(document["gazeTarget"], "auto")
        self.assertEqual(document["lipsyncActive"], False)
        self.assertEqual(document["position"], [0.0, 0.0, 0.0])
        self.assertEqual(document["framing"], "half")

    def test_document_has_no_private_fields(self) -> None:
        document = AVATAR.AvatarState().to_document()
        for key in document:
            self.assertFalse(key.startswith("_"))


class ParseCommandTest(unittest.TestCase):
    def parse(self, op: str, payload):
        return AVATAR.parse_command(op, payload)

    def test_presence_set(self) -> None:
        command = self.parse("avatar.presence.set", {"presence": "thinking"})
        self.assertEqual(command.presence, "thinking")

    def test_emotion_set(self) -> None:
        command = self.parse("avatar.emotion.set", {"emotion": "happy"})
        self.assertEqual(command.emotion, "happy")

    def test_expression_set(self) -> None:
        command = self.parse("avatar.expression.set", {"expression": "sad"})
        self.assertEqual(command.expression, "sad")

    def test_gesture(self) -> None:
        command = self.parse("avatar.gesture", {"gesture": "wave"})
        self.assertEqual(command.gesture, "wave")

    def test_animation_play_defaults(self) -> None:
        command = self.parse("avatar.animation.play", {"animation": "wave"})
        self.assertEqual(command.animation, "wave")
        self.assertFalse(command.loop)
        self.assertEqual(command.speed, 1.0)
        self.assertIsNone(command.duration)

    def test_animation_play_full(self) -> None:
        command = self.parse(
            "avatar.animation.play",
            {"animation": "idle", "loop": True, "speed": 1.5, "duration": 3.0},
        )
        self.assertTrue(command.loop)
        self.assertEqual(command.speed, 1.5)
        self.assertEqual(command.duration, 3.0)

    def test_animation_stop(self) -> None:
        command = self.parse("avatar.animation.stop", {})
        self.assertEqual(command.op, "avatar.animation.stop")

    def test_gaze_set_target_names(self) -> None:
        for target in ("user", "auto", "center"):
            command = self.parse("avatar.gaze.set", {"target": target})
            self.assertEqual(command.target, target)

    def test_gaze_set_point(self) -> None:
        command = self.parse(
            "avatar.gaze.set", {"target": {"x": 0.5, "y": 1.2, "z": -0.3}}
        )
        self.assertEqual(command.target, (0.5, 1.2, -0.3))

    def test_speech_begin(self) -> None:
        command = self.parse("avatar.speech.begin", {})
        self.assertEqual(command.op, "avatar.speech.begin")

    def test_speech_audio(self) -> None:
        payload = {"audio": AVATAR.base64_encode(b"\x00\x01"), "sampleRate": 16000}
        command = self.parse("avatar.speech.audio", payload)
        self.assertEqual(command.audio, b"\x00\x01")
        self.assertEqual(command.sample_rate, 16000)

    def test_speech_end_and_cancel(self) -> None:
        self.assertEqual(
            self.parse("avatar.speech.end", {}).op, "avatar.speech.end"
        )
        self.assertEqual(
            self.parse("avatar.speech.cancel", {}).op, "avatar.speech.cancel"
        )

    def test_transform_set_position_rotation_scale(self) -> None:
        command = self.parse(
            "avatar.transform.set",
            {"position": [0.1, 0.2, 0.3], "rotation": [0, 90, 0], "scale": 1.25},
        )
        self.assertEqual(command.position, (0.1, 0.2, 0.3))
        self.assertEqual(command.rotation, (0.0, 90.0, 0.0))
        self.assertEqual(command.scale, 1.25)

    def test_transform_set_requires_a_field(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse("avatar.transform.set", {})

    def test_framing_set(self) -> None:
        command = self.parse("avatar.framing.set", {"framing": "full"})
        self.assertEqual(command.framing, "full")

    def test_avatar_load_select_delete_take_ids(self) -> None:
        for op in ("avatar.load", "avatar.select", "avatar.delete"):
            command = self.parse(op, {"avatarId": "sample-1"})
            self.assertEqual(command.avatar_id, "sample-1")

    def test_avatar_unload_show_hide_have_no_payload(self) -> None:
        for op in ("avatar.unload", "avatar.show", "avatar.hide"):
            command = self.parse(op, {})
            self.assertEqual(command.op, op)

    def test_avatar_import_from_base64(self) -> None:
        blob = AVATAR.base64_encode(b"fake-vrm-bytes")
        command = self.parse(
            "avatar.import", {"name": "Sample Avatar", "data": blob}
        )
        self.assertEqual(command.name, "Sample Avatar")
        self.assertEqual(command.data, b"fake-vrm-bytes")
        self.assertIsNone(command.path)

    def test_avatar_import_from_path(self) -> None:
        command = self.parse(
            "avatar.import",
            {"name": "Sample", "path": "/tmp/sample.vrm"},
        )
        self.assertEqual(command.path, "/tmp/sample.vrm")
        self.assertIsNone(command.data)

    def test_avatar_import_requires_data_or_path(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse("avatar.import", {"name": "Sample"})

    def test_avatar_import_rejects_both_data_and_path(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse(
                "avatar.import",
                {"name": "S", "data": "AAAA", "path": "/tmp/s.vrm"},
            )

    def test_status_list_get_ops_accept_empty_payload(self) -> None:
        for op in ("avatar.status", "avatar.list", "avatar.transform.get", "avatar.framing.get"):
            command = self.parse(op, {})
            self.assertEqual(command.op, op)

    def test_unknown_op_rejected(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse("avatar.pets.morph", {})

    def test_unexpected_fields_rejected(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse("avatar.emotion.set", {"emotion": "happy", "mood": "x"})

    def test_invalid_enum_values_rejected(self) -> None:
        cases = {
            "avatar.presence.set": {"presence": "dancing"},
            "avatar.emotion.set": {"emotion": "smug"},
            "avatar.expression.set": {"expression": "wink"},
            "avatar.gesture": {"gesture": "cartwheel"},
            "avatar.framing.set": {"framing": "closeup"},
        }
        for op, payload in cases.items():
            with self.assertRaises(AVATAR.AvatarProtocolError):
                self.parse(op, payload)

    def test_animation_must_be_semantic_name(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse(
                "avatar.animation.play", {"animation": "clips/dance_v7.bvh"}
            )

    def test_speed_bounds_enforced(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse(
                "avatar.animation.play", {"animation": "idle", "speed": 0.0}
            )
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse(
                "avatar.animation.play", {"animation": "idle", "speed": 9.0}
            )

    def test_duration_bounds_enforced(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse(
                "avatar.animation.play", {"animation": "idle", "duration": 0.0}
            )
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse(
                "avatar.animation.play", {"animation": "idle", "duration": 999.0}
            )

    def test_scale_bounds_enforced(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse("avatar.transform.set", {"scale": 0.0})
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse("avatar.transform.set", {"scale": 100.0})

    def test_name_bounds_enforced(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse("avatar.import", {"name": "", "data": "AAAA"})
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse("avatar.import", {"name": "x" * 65, "data": "AAAA"})

    def test_speech_audio_requires_audio(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse("avatar.speech.audio", {})

    def test_speech_audio_rejects_invalid_base64(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse("avatar.speech.audio", {"audio": "!!!not-base64!!!"})

    def test_payload_must_be_mapping(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse("avatar.show", ["nope"])

    def test_sample_rate_validated(self) -> None:
        with self.assertRaises(AVATAR.AvatarProtocolError):
            self.parse(
                "avatar.speech.audio",
                {"audio": AVATAR.base64_encode(b"\x00\x00"), "sampleRate": -1},
            )


if __name__ == "__main__":
    unittest.main()
