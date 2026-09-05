import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_desktop.desktop import DesktopConfig, DesktopError, DesktopService


class FakeBackend:
    def __init__(self):
        self.launched = []

    def capabilities(self):
        return {"launch": True, "clipboard_read": False, "clipboard_write": False, "screenshot": False, "windows": False, "workspaces": False}

    def launch(self, argv):
        self.launched.append(tuple(argv))
        return {"status": "ok", "acknowledged": True, "pid": 7}

    def clipboard_read(self):
        return {"status": "unavailable", "reason": "clipboard-backend-unavailable"}

    def clipboard_write(self, text):
        return {"status": "unavailable", "reason": "clipboard-backend-unavailable"}

    def screenshot(self):
        return {"status": "unavailable", "reason": "screenshot-backend-unavailable"}

    def windows(self):
        return {"status": "unavailable", "reason": "window-backend-not-configured"}

    def workspaces(self):
        return {"status": "unavailable", "reason": "workspace-backend-not-configured"}


class DesktopTest(unittest.TestCase):
    def test_launch_only_accepts_configured_alias(self):
        backend = FakeBackend()
        service = DesktopService(DesktopConfig(applications={"browser": ("brave", "--new-window")}), backend)
        result = service.launch("browser")
        self.assertTrue(result["acknowledged"])
        self.assertEqual(backend.launched, [("brave", "--new-window")])
        denied = service.launch("$(touch /tmp/pwned)")
        self.assertEqual(denied["reason"], "unknown-application")
        self.assertEqual(len(backend.launched), 1)

    def test_configuration_rejects_string_commands_and_unbounded_argv(self):
        with self.assertRaises(DesktopError):
            DesktopConfig.load({"plugins": {"zara-desktop": {"applications": {"bad": "sh -c pwn"}}}})
        with self.assertRaises(DesktopError):
            DesktopConfig.load({"plugins": {"zara-desktop": {"applications": {"bad": ["x"] * 17}}}})

    def test_unsupported_features_degrade_explicitly(self):
        service = DesktopService(DesktopConfig(applications={}), FakeBackend())
        self.assertEqual(service.clipboard_read()["status"], "unavailable")
        self.assertEqual(service.screenshot()["status"], "unavailable")
        self.assertEqual(service.windows()["status"], "unavailable")
        self.assertEqual(service.workspaces()["status"], "unavailable")

    def test_status_exposes_capabilities_not_clipboard_content(self):
        service = DesktopService(DesktopConfig(applications={"browser": ("brave",)}), FakeBackend())
        status = service.status()
        self.assertEqual(status["configured_applications"], ["browser"])
        self.assertNotIn("content", status)


if __name__ == "__main__":
    unittest.main()
