import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_org_todos_service.install import install


class InstallTest(unittest.TestCase):
    def test_installs_entry_library_and_sync_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            result = install(home=root / "home", xdg_config_home=root / "config")
            self.assertTrue(result.plugin_entry.is_file())
            self.assertTrue((result.config_dir / "lib" / "zara_org_todos_service" / "plugin.py").is_file())
            self.assertTrue(result.sync_script.is_file())
            self.assertTrue(result.sync_script.stat().st_mode & 0o111)
