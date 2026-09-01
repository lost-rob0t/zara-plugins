"""Deterministic tests for the service plugin lifecycle and tool wiring."""

import unittest

from local_recall_test_support import LIB_ROOT, install_zara_stubs  # noqa: F401

install_zara_stubs()

from zara_local_recall_service import plugin as plugin_module  # noqa: E402


class FakeRuntime:
    def __init__(self, configuration: dict[str, object]):
        self.configuration = configuration


class ServicePluginTests(unittest.TestCase):
    def test_create_plugin_returns_named_service(self) -> None:
        instance = plugin_module.create_plugin()
        self.assertEqual(instance.metadata.name, "zara-local-recall")
        self.assertEqual(instance.metadata.version, "0.1.0")
        self.assertEqual(instance.metadata.api_version, "1")

    def test_start_reads_plugin_configuration(self) -> None:
        instance = plugin_module.create_plugin()
        runtime = FakeRuntime(
            {
                "enabled": True,
                "visual_selector": "current",
                "visual_maximum_records": 4,
            }
        )
        instance.start(runtime)
        self.assertEqual(instance._settings.visual_selector, "current")
        self.assertEqual(instance._settings.visual_maximum_records, 4)
        instance.stop()

    def test_disabled_start_registers_nothing(self) -> None:
        instance = plugin_module.create_plugin()
        runtime = FakeRuntime({"enabled": False})
        instance.start(runtime)
        self.assertFalse(instance._settings.enabled)
        instance.stop()

    def test_tools_are_lazily_built_and_cached(self) -> None:
        instance = plugin_module.create_plugin()
        instance.start(FakeRuntime({}))
        try:
            first = instance.tools()
        except ImportError:
            self.skipTest("langchain_core is not installed in the test environment")
            return
        second = instance.tools()
        self.assertEqual(len(first), 4)
        self.assertEqual(
            [tool.name for tool in first],
            [
                "local_recall_status",
                "local_recall_ask",
                "local_recall_search",
                "local_recall_explain_screen",
            ],
        )
        self.assertIs(first[0], second[0])
        instance.stop()


if __name__ == "__main__":
    unittest.main()
