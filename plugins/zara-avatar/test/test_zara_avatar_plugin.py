"""ZaraAvatarPlugin tests: lifecycle, HTTP API, failure isolation, shutdown."""

from __future__ import annotations

import json
import os
import shutil
import struct
import tempfile
import threading
import time
import unittest
import unittest.mock
import urllib.error
import urllib.request
from pathlib import Path

import avatar_test_support

AVATAR = avatar_test_support.load_avatar_module()

FIXTURES = Path(__file__).parent / "fixtures"
STUB_RENDERER = FIXTURES / "stub_renderer.py"


def _minimal_vrm() -> bytes:
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


class PluginTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.avatar_dir = Path(self.tmp.name) / "avatars"
        self.baseline_threads = set(threading.enumerate())

    def make_plugin(self, **config_overrides):
        config = {
            "port": 0,
            "avatar_directory": str(self.avatar_dir),
            "renderer_command": ["python3", "-X", "utf8", str(STUB_RENDERER)],
            "renderer_startup_timeout": 5.0,
            "renderer_request_timeout": 2.0,
            "request_size_limit": 65536,
        }
        config.update(config_overrides)
        plugin = AVATAR.create_plugin()
        runtime = avatar_test_support._FakeRuntime(configuration=config)
        plugin.start(runtime)
        self.addCleanup(self.stop_plugin, plugin)
        return plugin, runtime

    def stop_plugin(self, plugin) -> None:
        try:
            plugin.stop()
        except Exception:
            pass

    def base_url(self, plugin) -> str:
        address = plugin.server_address()
        return f"http://127.0.0.1:{address[1]}"

    def get(self, plugin, path) -> tuple[int, dict | bytes]:
        request = urllib.request.Request(self.base_url(plugin) + path)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            body = error.read()
            status = error.code
        try:
            return status, json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return status, body

    def post(self, plugin, path, payload) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            self.base_url(plugin) + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                body = response.read()
                status = response.status
        except urllib.error.HTTPError as error:
            body = error.read()
            status = error.code
        try:
            return status, json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return status, body

    def wait_for(self, predicate, timeout: float = 5.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.02)
        return predicate()


class PluginLifecycleTest(PluginTestCase):
    def test_metadata(self) -> None:
        plugin = AVATAR.create_plugin()
        self.assertEqual(plugin.metadata.name, "zara-avatar")
        self.assertEqual(plugin.metadata.api_version, "1")

    def test_start_starts_workers_and_server(self) -> None:
        plugin, runtime = self.make_plugin()
        self.assertIn("avatar-actor", runtime.worker_names)
        self.assertIn("avatar-event-pump", runtime.worker_names)
        self.assertIn("avatar-http-server", runtime.worker_names)
        status = plugin.status_document()
        self.assertEqual(status["state"], "running")

    def test_status_document_shape(self) -> None:
        plugin, _ = self.make_plugin()
        status = plugin.status_document()
        self.assertEqual(status["name"], "zara-avatar")
        self.assertIn("avatar", status)
        self.assertEqual(status["avatar"]["presence"], "idle")
        self.assertFalse(status["avatar"]["loaded"])

    def test_invalid_bind_address_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.make_plugin(bind_address="0.0.0.0")

    def test_disabled_plugin_starts_nothing(self) -> None:
        plugin, runtime = self.make_plugin(enabled=False)
        self.assertEqual(runtime.worker_names, [])
        self.assertIsNone(plugin.server_address())

    def test_missing_avatar_directory_created(self) -> None:
        nested = Path(self.tmp.name) / "deep" / "avatars"
        self.make_plugin(avatar_directory=str(nested))
        self.assertTrue(nested.exists())


class AvatarHttpTest(PluginTestCase):
    def test_status_route(self) -> None:
        plugin, _ = self.make_plugin()
        status, document = self.get(plugin, "/v1/avatar/status")
        self.assertEqual(status, 200)
        self.assertEqual(document["avatar"]["presence"], "idle")

    def test_list_route_empty(self) -> None:
        plugin, _ = self.make_plugin()
        status, document = self.get(plugin, "/v1/avatar/list")
        self.assertEqual(status, 200)
        self.assertEqual(document["avatars"], [])

    def test_import_load_select_flow(self) -> None:
        plugin, _ = self.make_plugin()
        blob = AVATAR.base64_encode(_minimal_vrm())
        status, document = self.post(
            plugin,
            "/v1/avatar/import",
            {"name": "Sample Avatar", "data": blob},
        )
        self.assertEqual(status, 200)
        avatar_id = document["avatarId"]
        status, _ = self.post(plugin, "/v1/avatar/select", {"avatarId": avatar_id})
        self.assertEqual(status, 200)
        status, document = self.get(plugin, "/v1/avatar/status")
        self.assertTrue(document["avatar"]["loaded"])
        self.assertEqual(document["avatar"]["avatarId"], avatar_id)
        self.assertEqual(document["avatar"]["selectedAvatarId"], avatar_id)

    def test_load_does_not_change_selection(self) -> None:
        plugin, _ = self.make_plugin()
        blob = AVATAR.base64_encode(_minimal_vrm())
        _, first = self.post(
            plugin, "/v1/avatar/import", {"name": "First", "data": blob}
        )
        _, second = self.post(
            plugin,
            "/v1/avatar/import",
            {
                "name": "Second",
                "data": AVATAR.base64_encode(_minimal_vrm() + b"\x01\x02"),
            },
        )
        self.post(plugin, "/v1/avatar/select", {"avatarId": first["avatarId"]})
        self.post(plugin, "/v1/avatar/load", {"avatarId": second["avatarId"]})
        _, document = self.get(plugin, "/v1/avatar/status")
        self.assertEqual(document["avatar"]["avatarId"], second["avatarId"])
        self.assertEqual(document["avatar"]["selectedAvatarId"], first["avatarId"])

    def test_import_rejects_corrupt_vrm(self) -> None:
        plugin, _ = self.make_plugin()
        status, document = self.post(
            plugin,
            "/v1/avatar/import",
            {"name": "Broken", "data": AVATAR.base64_encode(b"garbage")},
        )
        self.assertEqual(status, 400)
        self.assertIn("invalid", json.dumps(document).lower())

    def test_load_unknown_avatar_reports_error(self) -> None:
        plugin, _ = self.make_plugin()
        status, document = self.post(
            plugin, "/v1/avatar/load", {"avatarId": "missing-1"}
        )
        self.assertEqual(status, 400)
        self.assertIn("unknown", document["error"].lower())

    def test_expression_route(self) -> None:
        plugin, _ = self.make_plugin()
        status, _ = self.post(
            plugin, "/v1/avatar/expression", {"expression": "happy"}
        )
        self.assertEqual(status, 200)
        _, document = self.get(plugin, "/v1/avatar/status")
        self.assertEqual(document["avatar"]["expression"], "happy")

    def test_emotion_and_gesture_routes(self) -> None:
        plugin, _ = self.make_plugin()
        status, _ = self.post(plugin, "/v1/avatar/emotion", {"emotion": "annoyed"})
        self.assertEqual(status, 200)
        status, _ = self.post(plugin, "/v1/avatar/gesture", {"gesture": "wave"})
        self.assertEqual(status, 200)
        _, document = self.get(plugin, "/v1/avatar/status")
        self.assertEqual(document["avatar"]["emotion"], "annoyed")
        self.assertEqual(document["avatar"]["animation"], "wave")

    def test_speech_lifecycle_routes(self) -> None:
        plugin, _ = self.make_plugin()
        self.post(plugin, "/v1/avatar/speech/begin", {})
        pcm = b"\x00\x40" * 400
        status, _ = self.post(
            plugin,
            "/v1/avatar/speech/audio",
            {"audio": AVATAR.base64_encode(pcm)},
        )
        self.assertEqual(status, 200)
        status, _ = self.post(plugin, "/v1/avatar/speech/end", {})
        self.assertEqual(status, 200)
        _, document = self.get(plugin, "/v1/avatar/status")
        self.assertFalse(document["avatar"]["speaking"])
        self.assertFalse(document["avatar"]["lipsyncActive"])

    def test_speech_audio_without_begin_fails(self) -> None:
        plugin, _ = self.make_plugin()
        pcm = b"\x00\x40" * 400
        status, document = self.post(
            plugin,
            "/v1/avatar/speech/audio",
            {"audio": AVATAR.base64_encode(pcm)},
        )
        self.assertEqual(status, 400)

    def test_invalid_payload_rejected(self) -> None:
        plugin, _ = self.make_plugin()
        status, document = self.post(
            plugin, "/v1/avatar/emotion", {"emotion": "smug"}
        )
        self.assertEqual(status, 400)
        status, document = self.post(plugin, "/v1/avatar/emotion", {"mood": "x"})
        self.assertEqual(status, 400)

    def test_unknown_route_404(self) -> None:
        plugin, _ = self.make_plugin()
        status, _ = self.post(plugin, "/v1/avatar/wink", {})
        self.assertEqual(status, 404)

    def test_transform_and_framing_routes(self) -> None:
        plugin, _ = self.make_plugin()
        status, _ = self.post(
            plugin, "/v1/avatar/transform", {"position": [0.0, 1.0, 0.0]}
        )
        self.assertEqual(status, 200)
        status, document = self.get(plugin, "/v1/avatar/transform")
        self.assertEqual(document["position"], [0.0, 1.0, 0.0])
        status, _ = self.post(plugin, "/v1/avatar/framing", {"framing": "full"})
        self.assertEqual(status, 200)
        _, document = self.get(plugin, "/v1/avatar/framing")
        self.assertEqual(document["framing"], "full")

    def test_get_only_routes_reject_post_and_vice_versa(self) -> None:
        plugin, _ = self.make_plugin()
        status, _ = self.post(plugin, "/v1/avatar/status", {})
        self.assertEqual(status, 404)


class TurnStarted:
    """Stub named to serialize as the 'turn.started' runtime event."""

    turn_id = "stub"


class RuntimeEventIntegrationTest(PluginTestCase):
    def test_runtime_turn_event_moves_presence(self) -> None:
        plugin, runtime = self.make_plugin()
        runtime.subscription.publish(TurnStarted())
        self.assertTrue(
            self.wait_for(
                lambda: self.get(plugin, "/v1/avatar/status")[1]["avatar"][
                    "presence"
                ]
                == "thinking"
            )
        )


class FailureIsolationTest(PluginTestCase):
    def test_renderer_spawn_failure_degrades(self) -> None:
        plugin, _ = self.make_plugin(
            renderer_command=["/nonexistent/renderer-binary"],
        )
        # The startup probe runs on the actor thread; wait for it to converge.
        self.assertTrue(
            self.wait_for(
                lambda: self.get(plugin, "/v1/avatar/status")[1]["avatar"][
                    "renderer"
                ]["state"]
                == "unavailable",
                timeout=10.0,
            )
        )
        status, document = self.get(plugin, "/v1/avatar/status")
        self.assertEqual(status, 200)
        self.assertEqual(document["avatar"]["renderer"]["state"], "unavailable")
        # Semantics still work end to end.
        status, _ = self.post(plugin, "/v1/avatar/emotion", {"emotion": "happy"})
        self.assertEqual(status, 200)

    def test_select_after_failed_startup_degrades_and_recovers(self) -> None:
        plugin, _ = self.make_plugin(
            renderer_command=["false"],
            renderer_startup_timeout=1.0,
        )
        self.assertTrue(
            self.wait_for(
                lambda: plugin._actor._renderer_state == "unavailable",
                timeout=10.0,
            )
        )
        blob = AVATAR.base64_encode(_minimal_vrm())
        _, document = self.post(
            plugin, "/v1/avatar/import", {"name": "S", "data": blob}
        )
        status, _ = self.post(
            plugin, "/v1/avatar/load", {"avatarId": document["avatarId"]}
        )
        self.assertEqual(status, 503)
        status, document = self.get(plugin, "/v1/avatar/status")
        self.assertEqual(status, 200)
        self.assertFalse(document["avatar"]["loaded"])

    def test_load_with_broken_renderer_503(self) -> None:
        plugin, _ = self.make_plugin(
            renderer_command=["/nonexistent/renderer-binary"],
        )
        blob = AVATAR.base64_encode(_minimal_vrm())
        _, document = self.post(
            plugin, "/v1/avatar/import", {"name": "S", "data": blob}
        )
        status, _ = self.post(
            plugin, "/v1/avatar/load", {"avatarId": document["avatarId"]}
        )
        self.assertEqual(status, 503)
        status, document = self.get(plugin, "/v1/avatar/status")
        self.assertEqual(status, 200)
        self.assertFalse(document["avatar"]["loaded"])

    def test_renderer_crash_is_recovered(self) -> None:
        plugin, _ = self.make_plugin(max_renderer_restarts=3)
        blob = AVATAR.base64_encode(_minimal_vrm())
        _, document = self.post(
            plugin, "/v1/avatar/import", {"name": "S", "data": blob}
        )
        status, _ = self.post(
            plugin, "/v1/avatar/load", {"avatarId": document["avatarId"]}
        )
        self.assertEqual(status, 200)
        process = plugin.renderer_process()
        self.assertIsNotNone(process)
        process.kill()
        process.wait(timeout=5)
        self.assertTrue(
            self.wait_for(
                lambda: self.get(plugin, "/v1/avatar/status")[1]["avatar"][
                    "renderer"
                ]["state"]
                == "running"
            )
        )
        # The reloaded renderer serves requests again.
        status, _ = self.post(plugin, "/v1/avatar/hide", {})
        self.assertEqual(status, 200)


class ShutdownTest(PluginTestCase):
    def test_stop_terminates_renderer_and_threads(self) -> None:
        plugin, runtime = self.make_plugin()
        blob = AVATAR.base64_encode(_minimal_vrm())
        _, document = self.post(
            plugin, "/v1/avatar/import", {"name": "S", "data": blob}
        )
        self.post(plugin, "/v1/avatar/load", {"avatarId": document["avatarId"]})
        process = plugin.renderer_process()
        self.assertIsNotNone(process)
        runtime.close()
        plugin.stop()
        self.wait_for(lambda: process.poll() is not None, timeout=5)
        self.assertIsNotNone(process.poll())
        with self.assertRaises(AVATAR.ActorUnavailable):
            plugin.actor.submit(
                AVATAR.parse_command("avatar.status", {}), timeout=1.0
            )

    def test_stop_closes_subscription(self) -> None:
        plugin, runtime = self.make_plugin()
        plugin.stop()
        self.assertTrue(runtime.subscription.closed)

    def test_double_stop_is_safe(self) -> None:
        plugin, _ = self.make_plugin()
        plugin.stop()
        plugin.stop()


class StartupResilienceTest(PluginTestCase):
    def test_failed_start_resets_started_flag_and_allows_retry(self) -> None:
        plugin = AVATAR.create_plugin()
        runtime = avatar_test_support._FakeRuntime(
            configuration={
                "port": 0,
                "avatar_directory": str(self.avatar_dir),
                "renderer_command": [
                    "python3",
                    "-X",
                    "utf8",
                    str(STUB_RENDERER),
                ],
            }
        )
        original_server = AVATAR._AvatarHTTPServer

        class ExplodingServer:
            def __init__(self, address, plugin):
                raise OSError("simulated bind failure")

        AVATAR._AvatarHTTPServer = ExplodingServer
        try:
            with self.assertRaises(OSError):
                plugin.start(runtime)
        finally:
            AVATAR._AvatarHTTPServer = original_server

        self.assertFalse(plugin._started)
        self.assertFalse(plugin._stopping.is_set())

        plugin.start(runtime)
        self.addCleanup(self.stop_plugin, plugin)
        self.assertEqual(plugin.status_document()["state"], "running")
        self.assertEqual(
            runtime.worker_names,
            ["avatar-actor", "avatar-event-pump", "avatar-http-server"],
        )

    def test_avatar_directory_tilde_expands_to_home(self) -> None:
        with tempfile.TemporaryDirectory() as home:
            with unittest.mock.patch.dict(os.environ, {"HOME": home}):
                plugin, _ = self.make_plugin(
                    avatar_directory="~/zara-avatar-home-test/avatars"
                )
                expected = Path(home) / "zara-avatar-home-test" / "avatars"
                self.assertEqual(plugin._library.directory, expected)
                self.assertTrue(expected.is_dir())

    def test_start_does_not_block_on_renderer_probe(self) -> None:
        blocker = shutil.which("sleep")
        self.assertTrue(blocker, "sleep must exist to simulate a hung renderer")
        began = time.monotonic()
        plugin, _ = self.make_plugin(
            renderer_command=[blocker, "30"],
            renderer_startup_timeout=1.0,
        )
        elapsed = time.monotonic() - began
        self.assertLess(elapsed, 2.0)
        self.assertEqual(plugin.status_document()["state"], "running")
        self.assertTrue(
            self.wait_for(
                lambda: plugin._actor._renderer_state == "unavailable",
                timeout=10.0,
            )
        )


class RendererLoadTimeoutTest(PluginTestCase):
    def _import_and_load(self, plugin) -> tuple[int, dict]:
        blob = AVATAR.base64_encode(_minimal_vrm())
        _, document = self.post(
            plugin, "/v1/avatar/import", {"name": "S", "data": blob}
        )
        return self.post(
            plugin, "/v1/avatar/load", {"avatarId": document["avatarId"]}
        )

    def test_load_survives_slow_avatar_beyond_request_timeout(self) -> None:
        os.environ["STUB_LOAD_DELAY"] = "1.0"
        self.addCleanup(os.environ.pop, "STUB_LOAD_DELAY", None)
        plugin, _ = self.make_plugin(renderer_request_timeout=0.5)
        status, document = self._import_and_load(plugin)
        self.assertEqual(status, 200)
        self.assertTrue(document["loaded"])

    def test_load_respects_the_configured_load_timeout(self) -> None:
        os.environ["STUB_LOAD_DELAY"] = "1.2"
        self.addCleanup(os.environ.pop, "STUB_LOAD_DELAY", None)
        plugin, _ = self.make_plugin(
            renderer_request_timeout=0.5,
            renderer_load_timeout=0.8,
        )
        status, document = self._import_and_load(plugin)
        self.assertEqual(status, 400)
        self.assertIn("timed out after 0.8s", document["error"])


class RendererCommandResolutionTest(unittest.TestCase):
    def test_explicit_command_wins(self) -> None:
        resolved = AVATAR._resolve_renderer_command(
            {"renderer_command": ["electron", "main.mjs"]}
        )
        self.assertEqual(resolved, ["electron", "main.mjs"])

    def test_invalid_explicit_command_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AVATAR._resolve_renderer_command({"renderer_command": "electron"})
        with self.assertRaises(ValueError):
            AVATAR._resolve_renderer_command({"renderer_command": []})

    def test_env_override(self) -> None:
        previous = os.environ.get("ZARA_AVATAR_RENDERER")
        os.environ["ZARA_AVATAR_RENDERER"] = "electron /tmp/main.mjs"
        try:
            resolved = AVATAR._resolve_renderer_command({})
        finally:
            if previous is None:
                del os.environ["ZARA_AVATAR_RENDERER"]
            else:
                os.environ["ZARA_AVATAR_RENDERER"] = previous
        self.assertEqual(resolved, ["electron", "/tmp/main.mjs"])

    def test_unresolvable_returns_none(self) -> None:
        previous = os.environ.pop("ZARA_AVATAR_RENDERER", None)
        try:
            self.assertIsNone(
                AVATAR._resolve_renderer_command({}, renderer_roots=[])
            )
        finally:
            if previous is not None:
                os.environ["ZARA_AVATAR_RENDERER"] = previous

    def _make_roots(self, tmp) -> Path:
        root = Path(tmp) / "renderer"
        (root / "node_modules" / ".bin").mkdir(parents=True)
        (root / "node_modules" / ".bin" / "electron").write_text("")
        (root / "main.mjs").write_text("")
        return root

    def test_system_electron_with_suid_sandbox_is_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_roots(tmp)
            system = Path(tmp) / "electron41" / "electron"
            system.parent.mkdir(parents=True)
            system.write_text("")
            (system.parent / "chrome-sandbox").write_text("")
            os.chmod(system.parent / "chrome-sandbox", 0o4755)
            resolved = AVATAR._resolve_renderer_command(
                {},
                renderer_roots=[root],
                electron_candidates=[system],
            )
            self.assertEqual(resolved, [str(system), str(root / "main.mjs")])

    def test_bundled_electron_used_when_system_lacks_suid_helper(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_roots(tmp)
            system = Path(tmp) / "electron41" / "electron"
            system.parent.mkdir(parents=True)
            system.write_text("")
            (system.parent / "chrome-sandbox").write_text("")
            os.chmod(system.parent / "chrome-sandbox", 0o755)
            resolved = AVATAR._resolve_renderer_command(
                {},
                renderer_roots=[root],
                electron_candidates=[system],
            )
            self.assertEqual(
                resolved,
                [str(root / "node_modules" / ".bin" / "electron"), str(root / "main.mjs")],
            )

    def test_bundled_electron_used_without_system_electron(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._make_roots(tmp)
            resolved = AVATAR._resolve_renderer_command(
                {},
                renderer_roots=[root],
                electron_candidates=[],
            )
            self.assertEqual(
                resolved,
                [str(root / "node_modules" / ".bin" / "electron"), str(root / "main.mjs")],
            )

    def test_electron_root_is_discovered(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "renderer"
            electron = root / "node_modules" / ".bin" / "electron"
            electron.parent.mkdir(parents=True)
            electron.write_text("#!/bin/sh\n", encoding="utf-8")
            (root / "main.mjs").write_text("// renderer\n", encoding="utf-8")
            previous = os.environ.pop("ZARA_AVATAR_RENDERER", None)
            try:
                resolved = AVATAR._resolve_renderer_command(
                    {}, renderer_roots=[root], electron_candidates=[]
                )
            finally:
                if previous is not None:
                    os.environ["ZARA_AVATAR_RENDERER"] = previous
            self.assertEqual(
                resolved, [str(electron), str(root / "main.mjs")]
            )


class ArchitecturalGuardTest(unittest.TestCase):
    def test_avatar_plugin_has_no_pets_coupling(self) -> None:
        source = (
            Path(__file__).parents[1] / "zara-plugin" / "zara_avatar.py"
        ).read_text(encoding="utf-8")
        self.assertNotIn("zara.pets", source)
        self.assertNotIn("pets.", source)


if __name__ == "__main__":
    unittest.main()
