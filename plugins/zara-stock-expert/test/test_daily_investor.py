import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))


class DailyInvestorPrologTest(unittest.TestCase):
    def test_python_requires_a_unique_prolog_authorization_proof(self):
        from zara_stock_expert.prolog import StockProlog

        class Host:
            def __init__(self, backend, **options):
                self.calls = []
            def register(self, namespace, files):
                self.namespace = namespace
                self.files = files
            def explain(self, namespace, goal):
                self.calls.append((namespace, goal))
                return {'ok': True, 'results': ['Plan = plan([...],[live_execution])'], 'trace': ['fixture']}

        expert = StockProlog(Path('/tmp/private/stock.db'), 'daily-test', host_factory=Host)
        result = expert.authorize_daily_investor()
        self.assertTrue(result['authorized'])
        self.assertEqual(result['mode'], 'research')
        self.assertFalse(result['execution_eligible'])
        self.assertFalse(result['live_execution'])
        self.assertEqual(len(expert.host.calls), 1)
        goal = expert.host.calls[0][1]
        self.assertIn('stock_daily_investor_authorized(research)', goal)
        self.assertIn('stock_daily_investor_plan(research,Plan)', goal)
        self.assertIn('stock_daily_investor_explain(research,Explanation)', goal)

    def test_missing_prolog_proof_fails_closed(self):
        from zara_stock_expert.prolog import StockProlog

        class Host:
            def __init__(self, backend, **options):
                pass
            def register(self, namespace, files):
                pass
            def explain(self, namespace, goal):
                return {'ok': True, 'results': [], 'trace': []}

        expert = StockProlog(Path('/tmp/private/stock.db'), 'daily-test', host_factory=Host)
        with self.assertRaisesRegex(RuntimeError, 'no unique explanation'):
            expert.authorize_daily_investor()


if __name__ == '__main__':
    unittest.main()
