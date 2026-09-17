import os
import shutil
import subprocess
import unittest
from pathlib import Path

class NativeSessionTests(unittest.TestCase):
    def test_native_prolog_contract(self):
        swipl = shutil.which('swipl')
        if swipl is None:
            if os.environ.get('ZARA_REQUIRE_SWIPL') == '1':
                self.fail('Native SWI-Prolog is required by this gate')
            self.skipTest('SWI-Prolog unavailable; native semantics not verified')
        result = subprocess.run(
            [swipl, '-q', '-s', str(Path(__file__).with_name('session_tests.pl')),
             '-g', 'run_tests', '-t', 'halt'], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
