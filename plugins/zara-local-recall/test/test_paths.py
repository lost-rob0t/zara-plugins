"""Deterministic tests for runtime path resolution and settings."""

import unittest

from local_recall_test_support import LIB_ROOT  # noqa: F401

from zara_local_recall_service.paths import PluginSettings, RuntimePaths


class RuntimePathsTests(unittest.TestCase):
    def test_paths_resolve_under_xdg_runtime_dir(self) -> None:
        paths = RuntimePaths.from_environment(environ={"XDG_RUNTIME_DIR": "/run/user/1000"})
        self.assertEqual(str(paths.socket_path), "/run/user/1000/local-recall/control.sock")
        self.assertEqual(str(paths.token_path), "/run/user/1000/local-recall/session.token")

    def test_missing_runtime_dir_fails_closed(self) -> None:
        with self.assertRaises(RuntimeError):
            RuntimePaths.from_environment(environ={})

    def test_validate_rejects_missing_endpoints(self) -> None:
        paths = RuntimePaths.from_environment(environ={"XDG_RUNTIME_DIR": "/nonexistent-lr"})
        with self.assertRaises(RuntimeError):
            paths.validate()


class PluginSettingsTests(unittest.TestCase):
    def test_defaults(self) -> None:
        settings = PluginSettings.from_configuration({})
        self.assertTrue(settings.enabled)
        self.assertEqual(settings.visual_selector, "recent")
        self.assertEqual(settings.visual_maximum_records, 3)

    def test_bounds_are_enforced(self) -> None:
        settings = PluginSettings.from_configuration(
            {
                "visual_selector": "bounded_window",
                "visual_maximum_records": 99,
                "visual_timeout_seconds": 500,
                "cli_timeout_seconds": -3,
            }
        )
        self.assertEqual(settings.visual_selector, "recent")
        self.assertEqual(settings.visual_maximum_records, 3)
        self.assertEqual(settings.visual_timeout_seconds, 8.0)
        self.assertEqual(settings.cli_timeout_seconds, 15.0)

    def test_valid_values_pass_through(self) -> None:
        settings = PluginSettings.from_configuration(
            {
                "enabled": False,
                "visual_selector": "current",
                "visual_maximum_records": 5,
                "visual_timeout_seconds": 4,
                "cli_timeout_seconds": 30,
            }
        )
        self.assertFalse(settings.enabled)
        self.assertEqual(settings.visual_selector, "current")
        self.assertEqual(settings.visual_maximum_records, 5)
        self.assertEqual(settings.visual_timeout_seconds, 4.0)
        self.assertEqual(settings.cli_timeout_seconds, 30.0)


if __name__ == "__main__":
    unittest.main()
