import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]


class InstallerTests(unittest.TestCase):
    def test_install_seeds_config_without_overwriting_user_edits(self):
        with tempfile.TemporaryDirectory() as directory:
            env = dict(os.environ, HOME=directory, XDG_CONFIG_HOME=str(Path(directory)/'config'))
            command = [sys.executable, str(ROOT/'tools/zara-policy'), 'install']
            first = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            config = Path(env['XDG_CONFIG_HOME'])/'zarathushtra/plugins/zara-policy/config.pl'
            self.assertIn('option(mode, advice)', config.read_text())
            self.assertEqual(config.stat().st_mode & 0o777, 0o600)
            config.write_text('% keep my custom policy\n')
            second = subprocess.run(command, env=env, capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(config.read_text(), '% keep my custom policy\n')
            self.assertTrue((Path(directory)/'.zarathushtra/plugins/zara_policy.py').is_file())
            self.assertFalse((Path(env['XDG_CONFIG_HOME'])/'zarathushtra/config.toml').exists())
