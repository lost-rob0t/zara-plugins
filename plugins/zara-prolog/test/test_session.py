import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from zara_prolog.session import PrologSession, PrologSessionError


class Engine:
    def __init__(self):
        self.files = []
        self.goals = []

    def consult(self, path):
        self.files.append(Path(path))

    def query_once(self, goal):
        self.goals.append(goal)
        return {'Reply': json.dumps({'solutions': [{'X': '42'}], 'status': 'success'})}


class SessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.engine = Engine()
        self.session = PrologSession(Path(self.temp.name), engine_factory=lambda: self.engine)

    def test_start_loads_default_and_user_config(self):
        self.session.start()
        self.assertTrue((Path(self.temp.name) / 'config.pl').exists())
        self.assertTrue(any(path.name == 'session.pl' for path in self.engine.files))

    def test_existing_configuration_not_overwritten(self):
        config = Path(self.temp.name) / 'config.pl'
        config.write_text('% owned\n')
        self.session.start()
        self.assertEqual(config.read_text(), '% owned\n')

    def test_query_is_encoded_as_data_at_bridge(self):
        self.session.start()
        result = self.session.query('X = "\\\"), halt, (".')
        self.assertEqual(result['solutions'][0]['X'], '42')
        self.assertTrue(self.engine.goals[-1].startswith('zara_prolog_session:query_json('))
        self.assertIn('\\\\', self.engine.goals[-1])

    def test_query_before_start_fails(self):
        with self.assertRaises(PrologSessionError):
            self.session.query('true.')

    def test_invalid_queries_and_limits(self):
        self.session.start()
        for value in ['', 'x' * 8193, None, 42]:
            with self.subTest(value=str(value)[:10]), self.assertRaises(PrologSessionError):
                self.session.query(value)
        for value in [0, 65, True, '2']:
            with self.subTest(limit=value), self.assertRaises(PrologSessionError):
                self.session.query('true.', max_solutions=value)

    def test_stop_prevents_queries(self):
        self.session.start()
        self.session.stop()
        with self.assertRaises(PrologSessionError):
            self.session.query('true.')


if __name__ == '__main__':
    unittest.main()
