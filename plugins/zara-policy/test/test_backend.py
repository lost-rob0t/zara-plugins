from __future__ import annotations
import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from zara_policy.backend import PolicyBackend
from zara_policy.review import PolicyError

SETTINGS = {'mode': 'advise', 'max_repairs': 1, 'timeout_seconds': 20,
            'max_text_chars': 65536, 'profile': 'balanced'}

class Engine:
    def __init__(self):
        self.loads = []
        self.goals = []
        self.settings = dict(SETTINGS)
    def consult(self, path):
        self.loads.append(Path(path))
    def query_once(self, goal):
        self.goals.append(goal)
        if 'settings_json' in goal:
            return {'Reply': json.dumps(self.settings)}
        return {'Reply': '{"findings": []}'}

class BackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.engine = Engine()
        self.backend = PolicyBackend(self.root, engine_factory=lambda: self.engine)
    def test_default_config_is_created_and_loaded(self):
        self.backend.start()
        self.assertTrue((self.root / 'config.pl').is_file())
        self.assertEqual([path.name for path in self.engine.loads], ['engine.pl', 'config.pl'])
        self.assertEqual(self.backend.mode, 'advise')
        self.assertEqual(self.backend.max_repairs, 1)
    def test_existing_configuration_is_not_overwritten(self):
        (self.root / 'config.pl').write_text('% user owned\n')
        self.backend.start()
        self.assertEqual((self.root / 'config.pl').read_text(), '% user owned\n')
    def test_model_text_is_data_not_a_goal(self):
        self.backend.start()
        self.backend.inspect('hello), halt. %')
        goal = self.engine.goals[-1]
        self.assertTrue(goal.startswith('zara_policy:inspect_json('))
        self.assertIn('\\"text\\"', goal)
        self.assertNotIn('call(hello', goal)
    def test_code_is_masked_before_query(self):
        self.backend.start()
        self.backend.inspect('```\nall tests pass\n```\nPlain.')
        self.assertNotIn('all tests pass', self.engine.goals[-1])
    def test_invalid_settings_reject_startup(self):
        for key, value in [('mode', 'rewrite_forever'), ('max_repairs', 2),
                           ('max_repairs', True), ('timeout_seconds', float('nan')),
                           ('max_text_chars', 0), ('profile', 'missing')]:
            with self.subTest(key=key, value=value):
                self.engine.settings = dict(SETTINGS, **{key: value})
                with self.assertRaises(PolicyError):
                    self.backend.start()
                self.assertFalse(self.backend.ready)
    def test_invalid_text_does_not_query(self):
        self.backend.start()
        before = len(self.engine.goals)
        for value in (None, 42, 'a' * 65537):
            with self.assertRaises(PolicyError):
                self.backend.inspect(value)
        self.assertEqual(len(self.engine.goals), before)
    def test_stop_disables_scanning(self):
        self.backend.start()
        self.backend.stop()
        with self.assertRaises(PolicyError):
            self.backend.inspect('hello')
    def test_failures_do_not_return_empty_success(self):
        self.backend.start()
        self.engine.query_once = lambda goal: {'Reply': '{"error":"execution_failed"}'}
        with self.assertRaises(PolicyError):
            self.backend.inspect('hello')
    def test_busy_admission_is_bounded(self):
        self.backend.start()
        self.backend._admission.acquire()
        try:
            with self.assertRaises(PolicyError):
                asyncio.run(self.backend.inspect_async('hello'))
        finally:
            self.backend._admission.release()
