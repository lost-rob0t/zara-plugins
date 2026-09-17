import shutil
import subprocess
import unittest
from pathlib import Path


class PrologContractTest(unittest.TestCase):
    @unittest.skipUnless(shutil.which('swipl'), 'SWI-Prolog is not installed')
    def test_actual_exported_decision_and_explanation(self):
        kb = Path(__file__).resolve().parents[1] / 'lib' / 'zara_stock_expert' / 'stock_trading.pl'
        goal = (
            "stock_trade_decision(assessment(paper,[]),paper_candidate),"
            "stock_trade_decision(assessment(paper,[stale_quote]),blocked),"
            "stock_trade_explain(assessment(live,[]),explanation(blocked,[live_execution_unavailable])),"
            "stock_daily_investor_authorized(research),"
            "\\+stock_daily_investor_authorized(live),"
            "stock_daily_investor_plan(research,plan(_,Denied)),"
            "member(live_execution,Denied),member(broker_order,Denied),member(arbitrary_instrument,Denied),"
            "stock_daily_investor_explain(research,explanation(authorized,_)),"
            "stock_daily_investor_explain(live,explanation(blocked,[live_execution_unavailable])),"
            "\\+stock_trade_decision(assessment(other,[]),_),halt(0)"
        )
        result = subprocess.run(['swipl', '-q', '-s', str(kb), '-g', goal, '-t', 'halt(1)'],
                                capture_output=True, text=True, timeout=5, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
