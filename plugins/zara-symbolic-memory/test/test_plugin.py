import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

plugins = types.ModuleType("zara.plugins")


class PluginMetadata:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class ServicePlugin:
    pass


class StartupUnavailable:
    def __init__(self, reason):
        self.reason = reason


plugins.PluginMetadata = PluginMetadata
plugins.ServicePlugin = ServicePlugin
plugins.StartupUnavailable = StartupUnavailable
zara = types.ModuleType("zara")
zara.plugins = plugins
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", plugins)

from zara_symbolic_memory import plugin as plugin_module


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration


class PluginTest(unittest.TestCase):
    def test_metadata_and_disabled_embedding_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = plugin_module.create_plugin()
            result = instance.start(Runtime({"data_dir": directory, "embedding_backend": "disabled", "require_prolog": False}))
            self.assertIsNone(result)
            self.assertEqual(instance.metadata.name, "zara-symbolic-memory")
            self.assertEqual(instance.metadata.version, "0.1.0")
            status = instance.status()
            self.assertIn('"embedding_backend": null', status)
            instance.stop()

    def test_require_prolog_reports_unavailable_without_faking_readiness(self):
        with tempfile.TemporaryDirectory() as directory:
            instance = plugin_module.create_plugin()
            result = instance.start(Runtime({"data_dir": directory, "embedding_backend": "disabled", "require_prolog": True}))
            if instance.engine.ready():
                self.assertIsNone(result)
            else:
                self.assertIsInstance(result, StartupUnavailable)
                self.assertEqual(result.reason, "swipl-unavailable")
            instance.stop()


if __name__ == "__main__":
    unittest.main()
