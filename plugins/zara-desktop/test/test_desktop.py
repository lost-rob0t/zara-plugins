import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_desktop.core import DesktopController, DesktopError, DesktopEvent, FeatureUnavailable


class FakeBackend:
    name = "fake"

    def __init__(self):
        self.calls = []
        self.events = []

    def capabilities(self):
        return {"launch": True, "windows": True, "workspaces": True, "clipboard": True, "screenshot": False}

    def launch(self, app, args):
        self.calls.append(("launch", app, list(args)))
        return {"pid": 42, "app": app}

    def list_windows(self):
        return [{"id": "w1", "title": "Editor", "app": "emacs", "focused": True}]

    def focus_window(self, window_id):
        self.calls.append(("focus", window_id))
        return {"id": window_id, "focused": True}

    def close_window(self, window_id):
        self.calls.append(("close", window_id))
        return {"id": window_id, "closed": True}

    def list_workspaces(self):
        return [{"id": "1", "name": "dev", "active": True}]

    def switch_workspace(self, workspace_id):
        self.calls.append(("workspace", workspace_id))
        return {"id": workspace_id, "active": True}

    def clipboard_get(self):
        return "hello"

    def clipboard_set(self, text):
        self.calls.append(("clipboard", text))
        return {"bytes": len(text.encode())}

    def screenshot(self):
        raise FeatureUnavailable("screenshot", backend=self.name)

    def poll_events(self, limit):
        events, self.events = self.events[:limit], self.events[limit:]
        return events


class DesktopControllerTest(unittest.TestCase):
    def setUp(self):
        self.backend = FakeBackend()
        self.desktop = DesktopController(self.backend, max_text_bytes=16, max_events=4)

    def test_capabilities_are_explicit(self):
        result = self.desktop.status()
        self.assertEqual(result["backend"], "fake")
        self.assertFalse(result["capabilities"]["screenshot"])

    def test_launch_is_typed_not_shell(self):
        result = self.desktop.launch("emacs", ["--debug-init"])
        self.assertEqual(result["observed"]["pid"], 42)
        self.assertEqual(self.backend.calls[0], ("launch", "emacs", ["--debug-init"]))
        with self.assertRaises(DesktopError):
            self.desktop.launch("sh -c touch /tmp/pwned", [])

    def test_windows_and_workspaces_return_observed_state(self):
        self.assertTrue(self.desktop.windows()["windows"][0]["focused"])
        self.assertTrue(self.desktop.focus_window("w1")["observed"]["focused"])
        self.assertTrue(self.desktop.switch_workspace("1")["observed"]["active"])

    def test_clipboard_is_bounded(self):
        self.assertEqual(self.desktop.clipboard_get()["text"], "hello")
        with self.assertRaisesRegex(DesktopError, "too large"):
            self.desktop.clipboard_set("x" * 17)

    def test_unsupported_feature_is_honest(self):
        with self.assertRaisesRegex(FeatureUnavailable, "screenshot"):
            self.desktop.screenshot()

    def test_event_queue_is_bounded_and_provenanced(self):
        self.backend.events = [
            DesktopEvent("window.focused", {"window_id": str(i)}, "fake", float(i))
            for i in range(10)
        ]
        result = self.desktop.events(limit=10)
        self.assertEqual(len(result["events"]), 4)
        self.assertEqual(result["events"][0]["source"], "fake")


if __name__ == "__main__":
    unittest.main()
