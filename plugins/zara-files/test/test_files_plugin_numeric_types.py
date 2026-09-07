import importlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
sys.path.insert(0, str(ROOT / "zara-plugin"))

from zara_files.files import FileDomainError

PLUGIN = importlib.import_module("zara_files.plugin")


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration


class FilePluginNumericTypeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "root"
        self.root.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    def test_runtime_config_rejects_coercive_numeric_descriptors(self):
        for key in ("max_read_bytes", "max_results"):
            for value in (True, False, "64", 64.5):
                with self.subTest(key=key, value=value):
                    configuration = {
                        "plugins": {
                            "zara-files": {
                                "roots": [str(self.root)],
                                "max_read_bytes": 128,
                                "max_results": 8,
                                key: value,
                            }
                        }
                    }
                    plugin = PLUGIN.ZaraFilesPlugin()
                    with self.assertRaises(FileDomainError):
                        plugin.start(Runtime(configuration))


if __name__ == "__main__":
    unittest.main()
