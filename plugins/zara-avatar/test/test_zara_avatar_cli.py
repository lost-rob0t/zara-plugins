"""CLI tests for zara-avatar: standalone install and control without Emacs."""

from __future__ import annotations

import base64
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).parents[1]


def _load_cli():
    import importlib.machinery

    path = REPO / "tools" / "zara-avatar"
    loader = importlib.machinery.SourceFileLoader("zara_avatar_cli", str(path))
    spec = importlib.util.spec_from_loader("zara_avatar_cli", loader)
    module = importlib.util.module_from_spec(spec)
    sys_modules = __import__("sys").modules
    sys_modules["zara_avatar_cli"] = module
    loader.exec_module(module)
    return module


CLI = _load_cli()


class FakeClient:
    def __init__(self, status=200, document=None):
        self.requests = []
        self.status = status
        self.document = document or {}

    def request(self, method, path, payload=None):
        self.requests.append((method, path, payload))
        if self.status >= 400:
            raise CLI.AvatarHttpError(self.status, "boom")
        return self.status, self.document


def run_cli(argv, client=None):
    client = client or FakeClient()
    lines = []
    code = CLI.main(argv, client_factory=lambda base: client, out=lines.append)
    return code, client, lines


class RequestMappingTest(unittest.TestCase):
    def test_status_is_get(self) -> None:
        code, client, _ = self.run_cli(["status"])
        self.assertEqual(code, 0)
        self.assertEqual(client.requests[0][0], "GET")
        self.assertEqual(client.requests[0][1], "/v1/avatar/status")

    def test_show_hide_unload_are_empty_posts(self) -> None:
        for verb, path in (
            ("show", "/v1/avatar/show"),
            ("hide", "/v1/avatar/hide"),
            ("unload", "/v1/avatar/unload"),
            ("speech-begin", "/v1/avatar/speech/begin"),
            ("speech-end", "/v1/avatar/speech/end"),
            ("speech-cancel", "/v1/avatar/speech/cancel"),
            ("animation-stop", "/v1/avatar/animation/stop"),
        ):
            code, client, _ = self.run_cli([verb])
            self.assertEqual(code, 0, verb)
            self.assertEqual(client.requests[0], ("POST", path, {}))

    def test_semantic_values_map_to_ops(self) -> None:
        cases = [
            (["emotion", "happy"], "/v1/avatar/emotion", {"emotion": "happy"}),
            (
                ["expression", "surprised"],
                "/v1/avatar/expression",
                {"expression": "surprised"},
            ),
            (["gesture", "wave"], "/v1/avatar/gesture", {"gesture": "wave"}),
            (
                ["presence", "thinking"],
                "/v1/avatar/presence",
                {"presence": "thinking"},
            ),
            (["framing", "full"], "/v1/avatar/framing", {"framing": "full"}),
            (["gaze", "user"], "/v1/avatar/gaze", {"target": "user"}),
            (["animation", "play", "wave"], "/v1/avatar/animation/play", {"animation": "wave"}),
        ]
        for argv, path, payload in cases:
            code, client, _ = self.run_cli(argv)
            self.assertEqual(code, 0, argv)
            self.assertEqual(client.requests[0], ("POST", path, payload))

    def test_select_load_delete_take_avatar_id(self) -> None:
        for verb in ("select", "load", "delete"):
            code, client, _ = self.run_cli([verb, "sample-1"])
            self.assertEqual(code, 0)
            self.assertEqual(
                client.requests[0],
                ("POST", f"/v1/avatar/{verb}", {"avatarId": "sample-1"}),
            )

    def test_animation_play_flags(self) -> None:
        code, client, _ = self.run_cli(
            [
                "animation",
                "play",
                "wave",
                "--loop",
                "--speed",
                "1.5",
                "--duration",
                "2",
            ]
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            client.requests[0][2],
            {"animation": "wave", "loop": True, "speed": 1.5, "duration": 2.0},
        )

    def test_speech_audio_sends_base64(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".pcm") as handle:
            handle.write(b"\x01\x02\x03\x04")
            handle.flush()
            code, client, _ = self.run_cli(
                ["speech-audio", handle.name, "--sample-rate", "24000"]
            )
        self.assertEqual(code, 0)
        _, path, payload = client.requests[0]
        self.assertEqual(path, "/v1/avatar/speech/audio")
        self.assertEqual(base64.b64decode(payload["audio"]), b"\x01\x02\x03\x04")
        self.assertEqual(payload["sampleRate"], 24000)

    def test_import_reads_file(self) -> None:
        with tempfile.NamedTemporaryFile(suffix=".vrm") as handle:
            handle.write(b"glTF-fake")
            handle.flush()
            code, client, _ = self.run_cli(["import", "My Avatar", handle.name])
        self.assertEqual(code, 0)
        _, _, payload = client.requests[0]
        self.assertEqual(payload["name"], "My Avatar")
        self.assertEqual(base64.b64decode(payload["data"]), b"glTF-fake")

    def test_transform_partial_fields(self) -> None:
        code, client, _ = self.run_cli(
            ["transform", "--position", "0", "1", "0", "--scale", "1.5"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            client.requests[0][2],
            {"position": [0.0, 1.0, 0.0], "scale": 1.5},
        )

    def test_gaze_point(self) -> None:
        code, client, _ = self.run_cli(["gaze", "--point", "0.5", "1.2", "-0.3"])
        self.assertEqual(code, 0)
        self.assertEqual(
            client.requests[0][2], {"target": {"x": 0.5, "y": 1.2, "z": -0.3}}
        )

    def run_cli(self, argv):
        client = FakeClient()
        lines = []
        code = CLI.main(argv, client_factory=lambda base: client, out=lines.append)
        return code, client, lines


class ClientErrorMappingTest(unittest.TestCase):
    def test_http_error_prints_message_and_exits_two(self) -> None:
        client = FakeClient(status=400)
        code, text = self._run_capture(["show"], client)
        self.assertEqual(code, 2)
        self.assertIn("boom", text)

    def test_connection_error_exits_three(self) -> None:
        client = FakeClient()

        def broken(method, path, payload=None):
            raise CLI.AvatarConnectionError("connection refused")

        client.request = broken
        code, text = self._run_capture(["status"], client)
        self.assertEqual(code, 3)
        self.assertIn("not reachable", text)

    def _run_capture(self, argv, client):
        lines = []
        code = CLI.main(argv, client_factory=lambda base: client, out=lines.append)
        return code, " ".join(lines)


class InstallTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.plugins = Path(self.tmp.name) / "plugins"
        self.data = Path(self.tmp.name) / "data"

    def install(self, *extra):
        lines = []
        code = CLI.main(
            [
                "install",
                "--zara-plugins-dir",
                str(self.plugins),
                "--data-dir",
                str(self.data),
                "--skip-npm",
                *extra,
            ],
            client_factory=lambda base: FakeClient(),
            out=lines.append,
        )
        return code, " ".join(lines)

    def test_install_copies_plugin_and_renderer(self) -> None:
        code, output = self.install()
        self.assertEqual(code, 0, output)
        installed = self.plugins / "zara_avatar.py"
        self.assertTrue(installed.is_file())
        self.assertEqual(installed.stat().st_mode & 0o777, 0o644)
        renderer = self.data / "renderer"
        self.assertTrue((renderer / "main.mjs").is_file())
        self.assertTrue((renderer / "app.mjs").is_file())
        self.assertFalse((renderer / "node_modules").exists())

    def test_install_refuses_foreign_plugin(self) -> None:
        self.plugins.mkdir(parents=True)
        installed = self.plugins / "zara_avatar.py"
        installed.write_text("# someone else\n", encoding="utf-8")
        code, output = self.install()
        self.assertEqual(code, 4)
        self.assertIn("non-Zara", output)
        self.assertEqual(installed.read_text(encoding="utf-8"), "# someone else\n")

    def test_reinstall_updates_owned_file(self) -> None:
        code, _ = self.install()
        self.assertEqual(code, 0)
        code, output = self.install()
        self.assertEqual(code, 0)
        self.assertIn("installed", output.lower())

    def test_uninstall_removes_owned_plugin(self) -> None:
        self.install()
        lines = []
        code = CLI.main(
            [
                "uninstall",
                "--zara-plugins-dir",
                str(self.plugins),
            ],
            client_factory=lambda base: FakeClient(),
            out=lines.append,
        )
        self.assertEqual(code, 0)
        self.assertFalse((self.plugins / "zara_avatar.py").exists())

    def test_uninstall_refuses_foreign(self) -> None:
        self.plugins.mkdir(parents=True)
        foreign = self.plugins / "zara_avatar.py"
        foreign.write_text("# not zara\n", encoding="utf-8")
        lines = []
        code = CLI.main(
            [
                "uninstall",
                "--zara-plugins-dir",
                str(self.plugins),
            ],
            client_factory=lambda base: FakeClient(),
            out=lines.append,
        )
        self.assertEqual(code, 4)
        self.assertTrue(foreign.exists())

    def test_install_preserves_installed_node_modules(self) -> None:
        code, _ = self.install()
        renderer = self.data / "renderer"
        (renderer / "node_modules").mkdir()
        (renderer / "node_modules" / "keep.txt").write_text("keep", encoding="utf-8")
        code, _ = self.install()
        self.assertTrue((renderer / "node_modules" / "keep.txt").exists())


class DoctorTest(unittest.TestCase):
    def test_doctor_reports_states(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plugins = Path(tmp) / "plugins"
            data = Path(tmp) / "data"
            lines = []
            CLI.main(
                [
                    "install",
                    "--zara-plugins-dir",
                    str(plugins),
                    "--data-dir",
                    str(data),
                    "--skip-npm",
                ],
                client_factory=lambda base: FakeClient(),
                out=lines.append,
            )
            lines.clear()

            def unreachable(base):
                raise CLI.AvatarConnectionError("refused")

            code = CLI.main(
                [
                    "doctor",
                    "--zara-plugins-dir",
                    str(plugins),
                    "--data-dir",
                    str(data),
                ],
                client_factory=lambda base: FakeClient() if False else _BrokenClient(),
                out=lines.append,
            )
            text = " ".join(lines)
            self.assertIn("plugin", text)
            self.assertIn("renderer", text)


class _BrokenConnectionClient:
    def request(self, method, path, payload=None):
        raise CLI.AvatarConnectionError("refused")


class VerifyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.stub = REPO / "test" / "fixtures" / "stub_renderer.py"

    def _run_verify(self, *extra):
        lines = []
        code = CLI.main(
            ["verify", "--command", f"python3 -X utf8 {self.stub}", *extra],
            out=lines.append,
        )
        return code, lines

    def test_verify_passes_with_a_working_renderer(self) -> None:
        code, lines = self._run_verify(
            "--startup-timeout", "5", "--load-timeout", "5"
        )
        self.assertEqual(code, CLI.EXIT_OK, lines)
        self.assertTrue(any("PASS" in line for line in lines), lines)

    def test_verify_reports_a_renderer_that_never_signals_ready(self) -> None:
        lines = []
        code = CLI.main(
            ["verify", "--command", "false", "--startup-timeout", "2"],
            out=lines.append,
        )
        self.assertEqual(code, CLI.EXIT_UNREACHABLE, lines)
        self.assertTrue(any("ready" in line for line in lines), lines)

    def test_verify_reports_a_load_that_times_out(self) -> None:
        os.environ["STUB_LOAD_DELAY"] = "30"
        self.addCleanup(os.environ.pop, "STUB_LOAD_DELAY", None)
        code, lines = self._run_verify(
            "--startup-timeout", "5", "--load-timeout", "1"
        )
        self.assertEqual(code, CLI.EXIT_UNREACHABLE, lines)
        self.assertTrue(any("LoadAvatar" in line for line in lines), lines)


if __name__ == "__main__":
    unittest.main()
