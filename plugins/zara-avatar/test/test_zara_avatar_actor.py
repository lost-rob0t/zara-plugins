"""AvatarActor tests: serialization, semantics, speech lifecycle, isolation."""

from __future__ import annotations

import tempfile
import threading
import time
import unittest
from pathlib import Path

import avatar_test_support

AVATAR = avatar_test_support.load_avatar_module()

ALL_EXPRESSIONS = [
    "neutral",
    "happy",
    "sad",
    "angry",
    "annoyed",
    "relaxed",
    "surprised",
    "excited",
    "embarrassed",
]

TINY_DURATIONS = {name: 0.05 for name in AVATAR.SEMANTIC_ANIMATIONS}


class FakeRendererHost:
    """Scripted renderer stand-in for actor tests."""

    def __init__(self, *, expressions=None, fail=False, crash_after=None) -> None:
        self.requests: list[tuple[str, dict]] = []
        self.expressions = (
            list(expressions) if expressions is not None else list(ALL_EXPRESSIONS)
        )
        self.fail = fail
        self.crash_after = crash_after
        self.start_count = 0
        self.shutdown_count = 0
        self.restart_count = 0
        self._crashes = 0

    def start(self) -> None:
        self.start_count += 1

    @property
    def is_running(self) -> bool:
        if self.fail:
            return False
        if self.crash_after is not None and self._crashes >= self.crash_after:
            return False
        return True

    def request(self, command, params=None, *, timeout=None):
        self.requests.append((command, dict(params or {})))
        if self.fail or (
            self.crash_after is not None and self._crashes >= self.crash_after
        ):
            raise AVATAR.RendererRequestError("renderer is down")
        if command == "LoadAvatar":
            self._crashes += 1
            return {"command": command, "expressions": list(self.expressions)}
        if command == "SetVisemes":
            return {}
        return {}

    def restart(self) -> None:
        self.restart_count += 1
        if self.crash_after is not None:
            self._crashes = 0

    def shutdown(self) -> None:
        self.shutdown_count += 1

    def drain_events(self, limit=64):
        return []

    def commands(self, name):
        return [params for command, params in self.requests if command == name]


class ActorTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.library = AVATAR.AvatarLibrary(Path(self.tmp.name) / "avatars")
        self.renderer = FakeRendererHost()
        self.actor = self.make_actor(self.renderer)

    def make_actor(self, renderer) -> "AVATAR.AvatarActor":
        actor = AVATAR.AvatarActor(
            library=self.library,
            renderer_factory=lambda: renderer,
            durations=TINY_DURATIONS,
            restart_backoff=0.0,
        )
        actor._worker_thread = threading.Thread(
            target=actor.run, args=(threading.Event(),), daemon=True
        )
        actor._worker_thread.start()
        self.addCleanup(actor._worker_thread.join, 2.0)
        self.addCleanup(actor.shutdown)
        return actor

    def submit(self, op, payload=None):
        command = AVATAR.parse_command(op, payload or {})
        return self.actor.submit(command, timeout=5.0)

    def import_avatar(self, name="Sample"):
        return self.library.import_avatar(
            name, _minimal_vrm()
        )

    def load_avatar(self):
        record = self.import_avatar()
        self.submit("avatar.load", {"avatarId": record.avatar_id})
        return record


def _minimal_vrm() -> bytes:
    import json
    import struct

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


class SerializationTest(ActorTestCase):
    def test_commands_execute_in_order(self) -> None:
        results = []

        def flood():
            for index in range(20):
                result = self.actor.submit(
                    AVATAR.parse_command("avatar.emotion.set", {"emotion": "happy"})
                    if index % 2 == 0
                    else AVATAR.parse_command("avatar.emotion.set", {"emotion": "sad"}),
                    timeout=5.0,
                )
                results.append(result["emotion"])

        threads = [threading.Thread(target=flood) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        final = self.actor.status()["emotion"]
        self.assertIn(final, ("happy", "sad"))
        self.assertEqual(len(results), 80)

    def test_submit_after_shutdown_raises(self) -> None:
        self.actor.shutdown()
        with self.assertRaises(AVATAR.ActorUnavailable):
            self.actor.submit(
                AVATAR.parse_command("avatar.status", {}), timeout=1.0
            )


class LifecycleTest(ActorTestCase):
    def test_initial_status(self) -> None:
        status = self.actor.status()
        self.assertFalse(status["loaded"])
        self.assertFalse(status["visible"])
        self.assertEqual(status["presence"], "idle")
        self.assertEqual(status["emotion"], "neutral")

    def test_load_and_unload(self) -> None:
        record = self.load_avatar()
        status = self.actor.status()
        self.assertTrue(status["loaded"])
        self.assertEqual(status["avatarId"], record.avatar_id)
        self.submit("avatar.unload")
        status = self.actor.status()
        self.assertFalse(status["loaded"])
        self.assertIsNone(status["avatarId"])

    def test_load_unknown_avatar_fails(self) -> None:
        with self.assertRaises(AVATAR.ActorCommandError):
            self.submit("avatar.load", {"avatarId": "missing-1"})

    def test_show_hide_require_load(self) -> None:
        with self.assertRaises(AVATAR.ActorCommandError):
            self.submit("avatar.show")
        self.load_avatar()
        self.submit("avatar.show")
        self.assertTrue(self.actor.status()["visible"])
        self.submit("avatar.hide")
        self.assertFalse(self.actor.status()["visible"])

    def test_load_reports_capabilities(self) -> None:
        self.load_avatar()
        self.assertEqual(
            set(self.actor.available_expressions()), set(ALL_EXPRESSIONS)
        )


class SemanticsTest(ActorTestCase):
    def test_emotion_updates_expression(self) -> None:
        self.submit("avatar.emotion.set", {"emotion": "happy"})
        status = self.actor.status()
        self.assertEqual(status["emotion"], "happy")
        self.assertEqual(status["expression"], "happy")

    def test_emotion_falls_back_on_missing_expressions(self) -> None:
        self.renderer.expressions = ["neutral", "happy"]
        self.load_avatar()
        self.submit("avatar.emotion.set", {"emotion": "embarrassed"})
        status = self.actor.status()
        self.assertEqual(status["emotion"], "embarrassed")
        self.assertEqual(status["expression"], "happy")

    def test_expression_set_override(self) -> None:
        self.submit("avatar.expression.set", {"expression": "surprised"})
        self.assertEqual(self.actor.status()["expression"], "surprised")

    def test_presence_set_explicit(self) -> None:
        self.submit("avatar.presence.set", {"presence": "thinking"})
        self.assertEqual(self.actor.status()["presence"], "thinking")

    def test_runtime_events_infer_presence(self) -> None:
        self.actor.handle_runtime_event("turn.started")
        self.actor.flush()
        self.assertEqual(self.actor.status()["presence"], "thinking")
        self.actor.handle_runtime_event("runtime.idle")
        self.actor.flush()
        self.assertEqual(self.actor.status()["presence"], "idle")

    def test_inference_never_overrides_explicit_presence(self) -> None:
        self.submit("avatar.presence.set", {"presence": "listening"})
        self.actor.handle_runtime_event("turn.started")
        self.actor.flush()
        self.assertEqual(self.actor.status()["presence"], "listening")

    def test_explicit_reset_restores_inference(self) -> None:
        self.submit("avatar.presence.set", {"presence": "listening"})
        self.submit("avatar.presence.set", {"presence": "idle"})
        self.actor.handle_runtime_event("turn.started")
        self.actor.flush()
        self.assertEqual(self.actor.status()["presence"], "thinking")


class GestureAndAnimationTest(ActorTestCase):
    def setUp(self) -> None:
        ActorTestCase.setUp(self)
        self.load_avatar()

    def test_gesture_triggers_deterministic_animation(self) -> None:
        self.submit("avatar.gesture", {"gesture": "wave"})
        status = self.actor.status()
        self.assertEqual(status["animation"], "wave")
        plays = self.renderer.commands("PlayAnimation")
        self.assertEqual(plays[-1]["clip"], "wave")

    def test_gesture_returns_to_idle(self) -> None:
        self.submit("avatar.gesture", {"gesture": "nod"})
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if self.actor.status()["animation"] in AVATAR.SAFE_IDLE_CLIPS:
                break
            time.sleep(0.01)
        self.assertIn(self.actor.status()["animation"], AVATAR.SAFE_IDLE_CLIPS)

    def test_animation_play_with_options(self) -> None:
        self.submit(
            "avatar.animation.play",
            {"animation": "happy", "loop": True, "speed": 1.5},
        )
        status = self.actor.status()
        self.assertEqual(status["animation"], "happy")
        self.assertTrue(status["animationLoop"])
        self.assertEqual(status["animationSpeed"], 1.5)

    def test_animation_stop_returns_to_idle(self) -> None:
        self.submit("avatar.animation.play", {"animation": "happy", "loop": True})
        self.submit("avatar.animation.stop")
        self.assertIn(self.actor.status()["animation"], AVATAR.SAFE_IDLE_CLIPS)


class SpeechLifecycleTest(ActorTestCase):
    def setUp(self) -> None:
        ActorTestCase.setUp(self)
        self.load_avatar()
        self.submit("avatar.show")

    def test_speech_begin_sets_speaking(self) -> None:
        self.submit("avatar.speech.begin")
        status = self.actor.status()
        self.assertTrue(status["speaking"])
        self.assertEqual(status["presence"], "speaking")

    def test_speech_audio_drives_visemes(self) -> None:
        import struct
        import math

        samples = [
            int(0.6 * math.sin(2 * math.pi * 700 * i / 16000) * 32767)
            for i in range(640)
        ]
        pcm = struct.pack("<640h", *samples)
        self.submit("avatar.speech.begin")
        self.submit(
            "avatar.speech.audio",
            {"audio": AVATAR.base64_encode(pcm), "sampleRate": 16000},
        )
        self.assertTrue(self.actor.status()["lipsyncActive"])
        visemes = self.renderer.commands("SetVisemes")
        self.assertTrue(visemes)
        latest = visemes[-1]["weights"]
        self.assertTrue(any(weight > 0.0 for weight in latest.values()))

    def test_speech_end_restores_mouth_and_presence(self) -> None:
        self.submit("avatar.presence.set", {"presence": "listening"})
        self.submit("avatar.speech.begin")
        self.submit("avatar.speech.end")
        status = self.actor.status()
        self.assertFalse(status["speaking"])
        self.assertFalse(status["lipsyncActive"])
        self.assertEqual(status["presence"], "listening")
        visemes = self.renderer.commands("SetVisemes")
        latest = visemes[-1]["weights"]
        self.assertTrue(all(weight == 0.0 for weight in latest.values()))

    def test_speech_cancel_resets_mouth(self) -> None:
        self.submit("avatar.speech.begin")
        self.submit("avatar.speech.cancel")
        status = self.actor.status()
        self.assertFalse(status["speaking"])
        self.assertFalse(status["lipsyncActive"])
        visemes = self.renderer.commands("SetVisemes")
        latest = visemes[-1]["weights"]
        self.assertTrue(all(weight == 0.0 for weight in latest.values()))

    def test_audio_without_begin_rejected(self) -> None:
        with self.assertRaises(AVATAR.ActorCommandError):
            self.submit(
                "avatar.speech.audio",
                {"audio": AVATAR.base64_encode(b"\x00\x00")},
            )

    def test_speech_works_without_avatar_loaded(self) -> None:
        actor = self.make_actor(FakeRendererHost())
        actor.submit(AVATAR.parse_command("avatar.speech.begin", {}), timeout=5.0)
        status = actor.status()
        self.assertTrue(status["speaking"])
        actor.submit(AVATAR.parse_command("avatar.speech.end", {}), timeout=5.0)
        self.assertFalse(actor.status()["speaking"])


class TransformFramingTest(ActorTestCase):
    def test_transform_round_trip(self) -> None:
        self.submit(
            "avatar.transform.set",
            {"position": [0.5, 0.0, 0.0], "scale": 1.5},
        )
        document = self.submit("avatar.transform.get")
        self.assertEqual(document["position"], [0.5, 0.0, 0.0])
        self.assertEqual(document["scale"], 1.5)

    def test_framing_round_trip(self) -> None:
        self.submit("avatar.framing.set", {"framing": "full"})
        self.assertEqual(self.submit("avatar.framing.get")["framing"], "full")


class RendererIsolationTest(ActorTestCase):
    def test_semantics_survive_renderer_failure(self) -> None:
        self.renderer.fail = True
        self.submit("avatar.emotion.set", {"emotion": "happy"})
        self.assertEqual(self.actor.status()["emotion"], "happy")
        status = self.actor.status()
        self.assertEqual(status["renderer"]["state"], "unavailable")

    def test_load_fails_gracefully_without_renderer(self) -> None:
        self.renderer.fail = True
        record = self.import_avatar()
        with self.assertRaises(AVATAR.ActorCommandError):
            self.submit("avatar.load", {"avatarId": record.avatar_id})
        self.assertFalse(self.actor.status()["loaded"])
        self.assertEqual(self.actor.status()["renderer"]["state"], "unavailable")

    def test_renderer_restart_re_syncs_state(self) -> None:
        self.renderer.crash_after = 1
        self.load_avatar()
        self.submit("avatar.emotion.set", {"emotion": "happy"})
        self.renderer.fail = False
        self.renderer.crash_after = None
        self.actor.handle_renderer_exit()
        self.actor.flush()
        self.assertGreater(self.renderer.restart_count, 0)
        commands = [
            command for command, _ in self.renderer.requests
        ]
        self.assertIn("LoadAvatar", commands)
        self.assertIn("SetExpression", commands)


if __name__ == "__main__":
    unittest.main()
