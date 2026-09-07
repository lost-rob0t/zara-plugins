import subprocess
import sys
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_voice.domain import VoiceError
from zara_voice.player import PipeWirePlayer


class FakeStdin:
    def __init__(self):
        self.writes = []
        self.closed = False

    def write(self, data):
        self.writes.append(bytes(data))
        return len(data)

    def flush(self):
        return None

    def close(self):
        self.closed = True


class BlockingStdin(FakeStdin):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def write(self, data):
        self.started.set()
        self.release.wait(timeout=5.0)
        if self.closed:
            raise ValueError("closed")
        return super().write(data)

    def close(self):
        self.closed = True
        self.release.set()


class StubbornBlockingStdin(FakeStdin):
    def __init__(self):
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def write(self, data):
        self.started.set()
        self.release.wait(timeout=5.0)
        if self.closed:
            raise ValueError("closed")
        return super().write(data)

    def close(self):
        self.closed = True


class FakeProcess:
    def __init__(self, *, returncode=None, wait_timeout=False, stdin=None):
        self.stdin = stdin or FakeStdin()
        self.returncode = returncode
        self.wait_timeout = wait_timeout
        self.terminated = False
        self.killed = False
        self.wait_calls = []

    def poll(self):
        return self.returncode

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True
        self.returncode = -9

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        if self.wait_timeout and not self.killed:
            raise subprocess.TimeoutExpired("pw-play", timeout)
        if self.returncode is None:
            self.returncode = -15 if self.terminated else 0
        return self.returncode


class StuckProcess(FakeProcess):
    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        self.wait_calls.append(timeout)
        raise subprocess.TimeoutExpired("pw-play", timeout)


class MissingStdinStuckProcess(StuckProcess):
    def __init__(self):
        super().__init__()
        self.stdin = None


class PipeWirePlayerTests(unittest.TestCase):
    def artifact(self, **updates):
        value = {
            "audio": b"RIFFsafe-audio",
            "format": "wav",
            "sample_rate_hz": 24000,
            "duration_seconds": 0.4,
        }
        value.update(updates)
        return value

    def test_unavailable_binary_fails_closed_without_spawn(self):
        calls = []
        player = PipeWirePlayer(locator=lambda _: None, process_factory=lambda *args, **kwargs: calls.append((args, kwargs)))

        with self.assertRaisesRegex(VoiceError, "unavailable"):
            player.play(self.artifact())

        self.assertEqual(calls, [])

    def test_play_uses_fixed_pw_play_argv_and_returns_non_audible_process_evidence(self):
        calls = []
        process = FakeProcess()

        def spawn(argv, **kwargs):
            calls.append((list(argv), dict(kwargs)))
            return process

        player = PipeWirePlayer(
            locator=lambda name: "/usr/bin/pw-play",
            process_factory=spawn,
            id_factory=lambda: "opaque-1",
        )
        result = player.play(self.artifact())

        self.assertEqual(calls[0][0], ["/usr/bin/pw-play", "-"])
        self.assertFalse(calls[0][1].get("shell", False))
        self.assertEqual(result["playback_id"], "opaque-1")
        self.assertEqual(result["state"], "process_started")
        self.assertFalse(result["audible_confirmed"])
        self.assertNotIn("audio", result)
        self.assertNotIn(b"RIFFsafe-audio", repr(result).encode())

    def test_rejects_unsupported_format_and_oversized_audio_before_spawn(self):
        calls = []
        player = PipeWirePlayer(
            max_audio_bytes=8,
            locator=lambda name: "/usr/bin/pw-play",
            process_factory=lambda *args, **kwargs: calls.append((args, kwargs)),
        )

        with self.assertRaisesRegex(VoiceError, "format"):
            player.play(self.artifact(format="mp3"))
        with self.assertRaisesRegex(VoiceError, "limit"):
            player.play(self.artifact(audio=b"RIFF" * 3))

        self.assertEqual(calls, [])

    def test_id_allocation_failure_happens_before_process_spawn(self):
        calls = []
        player = PipeWirePlayer(
            locator=lambda name: "/usr/bin/pw-play",
            process_factory=lambda *args, **kwargs: calls.append((args, kwargs)),
            id_factory=lambda: "",
        )

        with self.assertRaisesRegex(VoiceError, "unique playback id"):
            player.play(self.artifact())

        self.assertEqual(calls, [])

    def test_missing_stdin_stubborn_child_remains_tracked_for_retry(self):
        process = MissingStdinStuckProcess()
        player = PipeWirePlayer(
            locator=lambda name: "/usr/bin/pw-play",
            process_factory=lambda *args, **kwargs: process,
            id_factory=lambda: "opaque-no-stdin",
            terminate_timeout=0.05,
            kill_timeout=0.05,
        )

        with self.assertRaisesRegex(VoiceError, "cleanup|cancellation"):
            player.play(self.artifact())

        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertIn("opaque-no-stdin", player._playbacks)

    def test_cancel_unknown_or_finished_id_is_rejected_as_stale(self):
        process = FakeProcess(returncode=0)
        player = PipeWirePlayer(
            locator=lambda name: "/usr/bin/pw-play",
            process_factory=lambda *args, **kwargs: process,
            id_factory=lambda: "opaque-2",
        )
        player.play(self.artifact())

        with self.assertRaisesRegex(VoiceError, "stale|unknown"):
            player.cancel("missing")
        with self.assertRaisesRegex(VoiceError, "stale|unknown"):
            player.cancel("opaque-2")

    def test_finished_process_with_live_writer_reports_cleanup_timeout_not_stale(self):
        stdin = StubbornBlockingStdin()
        process = FakeProcess(returncode=0, stdin=stdin)
        player = PipeWirePlayer(
            locator=lambda name: "/usr/bin/pw-play",
            process_factory=lambda *args, **kwargs: process,
            id_factory=lambda: "opaque-finished-writer",
            writer_timeout=0.05,
        )
        player.play(self.artifact())
        self.assertTrue(stdin.started.wait(timeout=0.5))

        try:
            with self.assertRaisesRegex(VoiceError, "writer cleanup exceeded"):
                player.cancel("opaque-finished-writer")
            self.assertIn("opaque-finished-writer", player._playbacks)
        finally:
            stdin.release.set()

    def test_cancel_terminates_waits_then_escalates_to_kill_with_bounds(self):
        process = FakeProcess(wait_timeout=True)
        player = PipeWirePlayer(
            locator=lambda name: "/usr/bin/pw-play",
            process_factory=lambda *args, **kwargs: process,
            id_factory=lambda: "opaque-3",
            terminate_timeout=0.25,
            kill_timeout=0.1,
        )
        player.play(self.artifact())

        self.assertTrue(player.cancel("opaque-3"))
        self.assertTrue(process.terminated)
        self.assertTrue(process.killed)
        self.assertEqual(process.wait_calls, [0.25, 0.1])
        with self.assertRaisesRegex(VoiceError, "stale|unknown"):
            player.cancel("opaque-3")

    def test_cancel_closes_input_and_joins_blocked_writer_before_success(self):
        stdin = BlockingStdin()
        process = FakeProcess(stdin=stdin)
        player = PipeWirePlayer(
            locator=lambda name: "/usr/bin/pw-play",
            process_factory=lambda *args, **kwargs: process,
            id_factory=lambda: "opaque-blocked",
            writer_timeout=0.25,
        )
        player.play(self.artifact())
        self.assertTrue(stdin.started.wait(timeout=0.5))

        self.assertTrue(player.cancel("opaque-blocked"))
        self.assertTrue(stdin.closed)
        self.assertFalse(any(thread.name.startswith("zara-voice-pw-play-opaque-b") for thread in threading.enumerate()))

    def test_double_process_timeout_still_checks_writer_teardown_before_error(self):
        stdin = BlockingStdin()
        process = StuckProcess(stdin=stdin)
        player = PipeWirePlayer(
            locator=lambda name: "/usr/bin/pw-play",
            process_factory=lambda *args, **kwargs: process,
            id_factory=lambda: "opaque-stuck",
            terminate_timeout=0.05,
            kill_timeout=0.05,
            writer_timeout=0.25,
        )
        player.play(self.artifact())
        self.assertTrue(stdin.started.wait(timeout=0.5))

        with self.assertRaisesRegex(VoiceError, "cancellation exceeded"):
            player.cancel("opaque-stuck")

        self.assertTrue(stdin.closed)
        self.assertFalse(any(thread.name.startswith("zara-voice-pw-play-opaque-s") for thread in threading.enumerate()))
        self.assertEqual(process.wait_calls, [0.05, 0.05])
        self.assertIn("opaque-stuck", player._playbacks)

    def test_close_surfaces_incomplete_cleanup_and_keeps_failed_resource_tracked(self):
        process = StuckProcess()
        player = PipeWirePlayer(
            locator=lambda name: "/usr/bin/pw-play",
            process_factory=lambda *args, **kwargs: process,
            id_factory=lambda: "opaque-close",
            terminate_timeout=0.05,
            kill_timeout=0.05,
        )
        player.play(self.artifact())

        with self.assertRaisesRegex(VoiceError, "close.*incomplete|cleanup.*incomplete"):
            player.close()

        self.assertIn("opaque-close", player._playbacks)

    def test_active_playback_count_is_bounded(self):
        spawned = []

        def spawn(*args, **kwargs):
            process = FakeProcess()
            spawned.append(process)
            return process

        ids = iter(["p1", "p2"])
        player = PipeWirePlayer(
            max_active_playbacks=1,
            locator=lambda name: "/usr/bin/pw-play",
            process_factory=spawn,
            id_factory=lambda: next(ids),
        )
        player.play(self.artifact())

        with self.assertRaisesRegex(VoiceError, "active playback"):
            player.play(self.artifact())

        self.assertEqual(len(spawned), 1)


if __name__ == "__main__":
    unittest.main()
