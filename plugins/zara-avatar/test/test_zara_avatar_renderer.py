"""Renderer host tests: child-process lifecycle, crash isolation, shutdown."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import avatar_test_support

AVATAR = avatar_test_support.load_avatar_module()

FIXTURES = Path(__file__).parent / "fixtures"
STUB_RENDERER = FIXTURES / "stub_renderer.py"


def stub_command() -> list[str]:
    return [sys.executable, "-X", "utf8", str(STUB_RENDERER)]


class RendererHostTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def make_host(self, **overrides) -> "AVATAR.RendererHost":
        settings = {
            "command": stub_command(),
            "startup_timeout": 5.0,
            "request_timeout": 2.0,
            "shutdown_grace": 2.0,
            "allowed_commands": AVATAR.RENDERER_COMMANDS
            | frozenset({"FailRequest", "HangRequest", "Crash"}),
        }
        settings.update(overrides)
        host = AVATAR.RendererHost(**settings)
        self.addCleanup(host.shutdown)
        return host

    def test_start_and_ready(self) -> None:
        host = self.make_host()
        host.start()
        self.assertTrue(host.is_running)

    def test_request_round_trip(self) -> None:
        host = self.make_host()
        host.start()
        result = host.request(
            "LoadAvatar",
            {"avatarId": "sample", "path": "/tmp/sample.vrm", "seed": 1},
        )
        self.assertEqual(result["command"], "LoadAvatar")

    def test_error_response_surfaces(self) -> None:
        host = self.make_host()
        host.start()
        with self.assertRaises(AVATAR.RendererRequestError) as caught:
            host.request("FailRequest", {"message": "nope"})
        self.assertIn("nope", str(caught.exception))

    def test_request_timeout(self) -> None:
        host = self.make_host()
        host.start()
        with self.assertRaises(AVATAR.RendererRequestError) as caught:
            host.request("HangRequest", {}, timeout=0.2)
        self.assertIn("timed out", str(caught.exception))

    def test_unknown_command_rejected(self) -> None:
        host = self.make_host()
        host.start()
        with self.assertRaises(ValueError):
            host.request("SelfDestruct", {})

    def test_crash_detected_with_event(self) -> None:
        host = self.make_host()
        host.start()
        with self.assertRaises(AVATAR.RendererRequestError):
            host.request("Crash", {})
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and host.is_running:
            time.sleep(0.02)
        self.assertFalse(host.is_running)
        events = host.drain_events()
        names = [event["event"] for event in events]
        self.assertIn("rendererExited", names)

    def test_events_from_renderer_surface(self) -> None:
        host = self.make_host()
        host.start()
        host.request("LoadAvatar", {"avatarId": "a", "path": "p", "seed": 1})
        events = host.drain_events()
        self.assertIn(
            "avatarLoaded", [event["event"] for event in events]
        )

    def test_shutdown_terminates_child(self) -> None:
        host = self.make_host()
        host.start()
        process = host.process
        host.shutdown()
        self.assertFalse(host.is_running)
        self.assertIsNotNone(process.poll())
        with self.assertRaises(AVATAR.RendererRequestError):
            host.request("LoadAvatar", {})

    def test_shutdown_without_start_is_safe(self) -> None:
        host = self.make_host()
        host.shutdown()

    def test_double_start_rejected(self) -> None:
        host = self.make_host()
        host.start()
        with self.assertRaises(RuntimeError):
            host.start()

    def test_renderer_exits_on_parent_stdin_close(self) -> None:
        # Orphan-prevention contract: if the plugin dies without sending
        # Shutdown, the child must exit when the stdin pipe closes.
        host = self.make_host()
        host.start()
        process = host.process
        process.stdin.close()
        self.assertIsNotNone(
            process.poll() if process.wait(timeout=5) == 0 else None
        )

    def test_restart_after_crash(self) -> None:
        host = self.make_host()
        host.start()
        with self.assertRaises(AVATAR.RendererRequestError):
            host.request("Crash", {})
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline and host.is_running:
            time.sleep(0.02)
        host.restart()
        self.assertTrue(host.is_running)
        result = host.request("LoadAvatar", {"avatarId": "a", "path": "p", "seed": 1})
        self.assertEqual(result["command"], "LoadAvatar")

    def test_startup_timeout_raises(self) -> None:
        environment = dict(os.environ)
        environment["STUB_RENDERER_STARTUP_DELAY"] = "5"
        host = self.make_host(
            startup_timeout=0.5,
            shutdown_grace=0.3,
            environment=environment,
        )
        with self.assertRaises(AVATAR.RendererUnavailable):
            host.start()
        self.assertFalse(host.is_running)

    def test_bounded_stdin(self) -> None:
        host = self.make_host()
        host.start()
        with self.assertRaises(ValueError):
            host.request("LoadAvatar", {"blob": "x" * (AVATAR.MAX_RENDERER_PAYLOAD + 1)})


if __name__ == "__main__":
    unittest.main()
