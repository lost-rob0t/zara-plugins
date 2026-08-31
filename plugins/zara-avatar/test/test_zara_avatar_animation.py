"""Animation subsystem tests: playback, queue, crossfade, idle scheduling."""

from __future__ import annotations

import unittest

import avatar_test_support

AVATAR = avatar_test_support.load_avatar_module()


def play_commands(commands):
    return [
        command
        for command in commands
        if isinstance(command, AVATAR.RendererPlayAnimation)
    ]


class GestureMappingTest(unittest.TestCase):
    def test_gestures_map_deterministically(self) -> None:
        controller = AVATAR.AnimationController(seed=1)
        for gesture in AVATAR.GESTURES:
            controller.reset()
            commands = controller.gesture(gesture)
            plays = play_commands(commands)
            self.assertEqual(len(plays), 1)
            self.assertEqual(plays[0].clip, gesture)
            self.assertFalse(plays[0].loop)

    def test_gesture_returns_to_idle_after_finish(self) -> None:
        controller = AVATAR.AnimationController(seed=1)
        controller.gesture("wave")
        commands = controller.finish()
        plays = play_commands(commands)
        self.assertEqual(len(plays), 1)
        self.assertIn(plays[0].clip, AVATAR.SAFE_IDLE_CLIPS)

    def test_unknown_gesture_rejected(self) -> None:
        controller = AVATAR.AnimationController(seed=1)
        with self.assertRaises(ValueError):
            controller.gesture("cartwheel")


class PlaybackTest(unittest.TestCase):
    def test_play_returns_play_animation_with_params(self) -> None:
        controller = AVATAR.AnimationController(seed=1)
        commands = controller.play("happy", loop=False, speed=1.5, duration=2.0)
        plays = play_commands(commands)
        self.assertEqual(len(plays), 1)
        self.assertEqual(plays[0].clip, "happy")
        self.assertFalse(plays[0].loop)
        self.assertEqual(plays[0].speed, 1.5)
        self.assertEqual(plays[0].duration, 2.0)
        self.assertTrue(plays[0].crossfade > 0.0)

    def test_play_rejects_non_semantic_clip(self) -> None:
        controller = AVATAR.AnimationController(seed=1)
        with self.assertRaises(ValueError):
            controller.play("dances/disco_v7.bvh")

    def test_stop_clears_queue_and_returns_to_idle(self) -> None:
        controller = AVATAR.AnimationController(seed=1)
        controller.play("happy", duration=1.0)
        controller.play("sad", duration=1.0)
        commands = controller.stop()
        plays = play_commands(commands)
        self.assertEqual(len(controller.pending), 0)
        self.assertEqual(len(plays), 1)
        self.assertIn(plays[0].clip, AVATAR.SAFE_IDLE_CLIPS)

    def test_queue_drains_in_order_then_idles(self) -> None:
        controller = AVATAR.AnimationController(seed=1)
        controller.play("happy", duration=1.0)
        controller.play("sad", duration=1.0)
        self.assertEqual(len(controller.pending), 1)
        first = play_commands(controller.finish())
        self.assertEqual(first[0].clip, "sad")
        second = play_commands(controller.finish())
        self.assertIn(second[0].clip, AVATAR.SAFE_IDLE_CLIPS)

    def test_looping_clip_does_not_finish(self) -> None:
        controller = AVATAR.AnimationController(seed=1)
        controller.play("idle", loop=True)
        self.assertEqual(controller.finish(), [])

    def test_emotion_clip_plays_once_then_idles(self) -> None:
        controller = AVATAR.AnimationController(seed=1)
        controller.play("excited")
        commands = controller.finish()
        plays = play_commands(commands)
        self.assertEqual(len(plays), 1)
        self.assertIn(plays[0].clip, AVATAR.SAFE_IDLE_CLIPS)


class IdleSchedulingTest(unittest.TestCase):
    def test_idle_only_draws_safe_clips(self) -> None:
        controller = AVATAR.AnimationController(seed=7)
        for _ in range(40):
            clip = controller.next_idle()
            self.assertIn(clip, AVATAR.SAFE_IDLE_CLIPS)

    def test_idle_shuffle_is_non_repeating_per_cycle(self) -> None:
        controller = AVATAR.AnimationController(seed=3)
        drawn = [controller.next_idle() for _ in range(len(AVATAR.SAFE_IDLE_CLIPS))]
        self.assertEqual(sorted(drawn), sorted(AVATAR.SAFE_IDLE_CLIPS))
        self.assertEqual(len(drawn), len(set(drawn)))

    def test_seeded_scheduling_is_deterministic(self) -> None:
        first = AVATAR.AnimationController(seed=42)
        second = AVATAR.AnimationController(seed=42)
        sequence_first = [first.next_idle() for _ in range(20)]
        sequence_second = [second.next_idle() for _ in range(20)]
        self.assertEqual(sequence_first, sequence_second)

    def test_safe_idle_set_excludes_dances_and_reactions(self) -> None:
        for clip in AVATAR.SAFE_IDLE_CLIPS:
            self.assertIn(clip, AVATAR.SEMANTIC_ANIMATIONS)
        self.assertNotIn("wave", AVATAR.SAFE_IDLE_CLIPS)


class ClipDurationsTest(unittest.TestCase):
    def test_every_semantic_clip_has_a_default_duration(self) -> None:
        for clip in AVATAR.SEMANTIC_ANIMATIONS:
            self.assertIn(clip, AVATAR.CLIP_DURATIONS)
            self.assertTrue(AVATAR.CLIP_DURATIONS[clip] > 0.0)

    def test_play_fills_default_duration_for_non_loop(self) -> None:
        controller = AVATAR.AnimationController(seed=1)
        plays = play_commands(controller.play("happy"))
        self.assertEqual(plays[0].duration, AVATAR.CLIP_DURATIONS["happy"])


if __name__ == "__main__":
    unittest.main()
