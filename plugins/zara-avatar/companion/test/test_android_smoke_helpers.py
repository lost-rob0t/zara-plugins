import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('android_smoke', Path(__file__).resolve().parents[1] / 'e2e/android_smoke.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

class SmokeHelpers(unittest.TestCase):
    def test_bounds_are_bounded(self):
        self.assertEqual(module.center('[10,20][110,80]'), (35,50))
        for value in ['invalid', '[1,1][1,1]', '[2,2][1,1]']:
            with self.assertRaises(ValueError):
                module.center(value)

    def test_activity_is_not_an_overlay(self):
        dump = '\n Window #0 Window{ai.zara.companion}:\n mAttrs={ty=BASE_APPLICATION}\n'
        self.assertEqual(module.overlay_windows(dump), [])

    def test_overlay_is_package_scoped(self):
        dump = '\n Window #0 Window{other.app}:\n mAttrs={ty=APPLICATION_OVERLAY}\n Window #1 Window{ai.zara.companion}:\n mAttrs={ty=APPLICATION_OVERLAY fl=NOT_TOUCHABLE}\n'
        self.assertEqual(len(module.overlay_windows(dump)), 1)
        self.assertIn('NOT_TOUCHABLE', module.overlay_windows(dump)[0])
