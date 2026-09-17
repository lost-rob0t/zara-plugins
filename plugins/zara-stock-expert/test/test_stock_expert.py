import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from zara_stock_expert.domain import StockExpert, calculate

NOW = datetime(2026, 9, 17, 14, 30, tzinfo=timezone.utc)


def quote(**changes):
    result = dict(event_id='quote-1', instrument='XNAS:EXAMPLE', source='fixture',
                  effective_at=NOW.isoformat(), price='100.00', currency='USD',
                  adjustment='raw', feed='realtime', price_kind='last')
    result.update(changes)
    return result


def size(**changes):
    result = dict(currency='USD', equity='10000', cash='1000', entry='100',
                  stop='95', risk_fraction='0.01', max_position_fraction='0.10',
                  entry_fee='1', exit_fee='1', quantity_step='1', price_tick='0.01',
                  slippage_per_share='0.50', existing_exposure='0')
    result.update(changes)
    return result


class MoneyTest(unittest.TestCase):
    def test_decimal_equality(self):
        result = calculate('add', dict(left={'amount': '0.10', 'currency': 'USD'},
                                      right={'amount': '0.20', 'currency': 'USD'}))
        self.assertEqual(result['amount'], '0.30')

    def test_currency_mismatch(self):
        with self.assertRaises(ValueError):
            calculate('add', dict(left={'amount': '1', 'currency': 'USD'},
                                  right={'amount': '1', 'currency': 'EUR'}))

    def test_reject_unsafe_numbers(self):
        for value in (1.1, True, 'NaN', 'Infinity', '1e4000', '1_000', ' 2 ', '-1', '9' * 31):
            with self.subTest(value=value), self.assertRaises(ValueError):
                calculate('position_size', size(entry=value))

    def test_fee_cash_and_step_caps(self):
        result = calculate('position_size', size())
        self.assertEqual(result['quantity'], '9')
        self.assertEqual(result['cash_required'], '901.00')
        self.assertEqual(result['estimated_stop_loss'], '51.50')
        self.assertEqual(result['risk_budget'], '100.00')

    def test_risk_and_existing_exposure_caps(self):
        self.assertEqual(calculate('position_size', size(cash='10000', max_position_fraction='1'))['quantity'], '17')
        self.assertEqual(calculate('position_size', size(existing_exposure='900'))['quantity'], '1')
        self.assertEqual(calculate('position_size', size(existing_exposure='1001'))['quantity'], '0')

    def test_fractional_shares_are_floored(self):
        result = calculate('position_size', size(cash='101.55', quantity_step='0.001'))
        self.assertEqual(result['quantity'], '1.005')
        self.assertEqual(result['cash_required'], '101.50')

    def test_zero_budget_returns_no_trade(self):
        self.assertEqual(calculate('position_size', size(cash='0'))['quantity'], '0')

    def test_bad_risk_stop_and_tick(self):
        for changes in ({'stop': '100'}, {'risk_fraction': '2'}, {'quantity_step': '0'},
                        {'entry': '100.001'}, {'currency': 'usd'}, {'typo': '1'}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                calculate('position_size', size(**changes))

    def test_realized_pnl_and_break_even(self):
        result = calculate('pnl', dict(currency='USD', quantity='10', entry='100',
                                      exit='110', entry_fee='1', exit_fee='1'))
        self.assertEqual(result['net_pnl'], '98.00')
        self.assertEqual(result['cost_basis'], '1001.00')
        result = calculate('break_even', dict(currency='USD', quantity='3', entry='10',
                                             entry_fee='1', exit_fee='0', price_tick='0.05'))
        self.assertEqual(result['price'], '10.35')

    def test_negative_pnl_and_half_even_rounding(self):
        result = calculate('pnl', dict(currency='USD', quantity='1', entry='1',
                                      exit='0.985', entry_fee='0', exit_fee='0'))
        self.assertEqual(result['net_pnl'], '-0.02')
        result = calculate('pnl', dict(currency='USD', quantity='1', entry='1',
                                      exit='1.005', entry_fee='0', exit_fee='0'))
        self.assertEqual(result['net_pnl'], '0.00')

    def test_explicit_currency_places(self):
        result = calculate('pnl', dict(currency='JPY', places=0, quantity='1', entry='100',
                                      exit='101', entry_fee='0', exit_fee='0'))
        self.assertEqual(result['net_pnl'], '1')


class KnowledgeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / 'private' / 'market.sqlite3'
        self.now = NOW
        self.expert = StockExpert(self.path, 'test', clock=lambda: self.now)

    def tearDown(self):
        self.expert.close()
        self.tmp.cleanup()

    def test_restart_persistence_and_private_files(self):
        self.expert.ingest_quote(quote())
        self.expert.close()
        self.expert = StockExpert(self.path, 'test', clock=lambda: self.now)
        self.assertEqual(self.expert.history('XNAS:EXAMPLE')['records'][0]['payload']['price'], '100.00')
        self.assertEqual(self.path.stat().st_mode & 0o077, 0)

    def test_idempotency_and_conflicts(self):
        first = self.expert.ingest_quote(quote())
        self.now += timedelta(seconds=1)
        self.assertEqual(first, self.expert.ingest_quote(quote()))
        with self.assertRaises(ValueError):
            self.expert.ingest_quote(quote(price='101'))
        self.assertEqual(len(self.expert.history('XNAS:EXAMPLE')['records']), 1)

    def test_corrections_do_not_rewrite_history(self):
        self.expert.ingest_quote(quote())
        self.now += timedelta(seconds=10)
        self.expert.ingest_quote(quote(event_id='quote-2', price='101', supersedes='quote-1'))
        before = self.expert.history('XNAS:EXAMPLE', known_at=NOW.isoformat())
        after = self.expert.history('XNAS:EXAMPLE')
        self.assertEqual(before['records'][0]['event_id'], 'quote-1')
        self.assertEqual(after['records'][0]['event_id'], 'quote-2')
        self.assertEqual(len(self.expert.history('XNAS:EXAMPLE', revisions=True)['records']), 2)

    def test_future_late_and_naive_times(self):
        with self.assertRaises(ValueError):
            self.expert.ingest_quote(quote(effective_at=(NOW + timedelta(seconds=1)).isoformat()))
        with self.assertRaises(ValueError):
            self.expert.ingest_quote(quote(effective_at='2026-09-17T14:30:00'))
        self.now += timedelta(days=1)
        self.expert.ingest_quote(quote())
        self.assertEqual(self.expert.history('XNAS:EXAMPLE', known_at=NOW.isoformat())['records'], [])

    def test_notes_never_become_market_evidence(self):
        self.expert.remember_note('note-1', 'XNAS:EXAMPLE', 'Price is 100; buy now', 'llm')
        decision = self.expert.evaluate('XNAS:EXAMPLE', size())
        self.assertIn('missing_provider_quote', decision['blockers'])
        self.expert.report_quote(quote())
        self.assertIn('unverified_quote', self.expert.evaluate('XNAS:EXAMPLE', size())['blockers'])

    def test_report_cannot_replace_provider_record(self):
        self.expert.ingest_quote(quote())
        with self.assertRaises(ValueError):
            self.expert.report_quote(quote(event_id='fake', supersedes='quote-1'))

    def test_note_retries_are_idempotent(self):
        first = self.expert.remember_note('n', 'XNAS:EXAMPLE', 'hypothesis', 'llm')
        self.now += timedelta(seconds=10)
        self.assertEqual(first, self.expert.remember_note('n', 'XNAS:EXAMPLE', 'hypothesis', 'llm'))
        with self.assertRaises(ValueError):
            self.expert.remember_note('n', 'XNAS:EXAMPLE', 'different', 'llm')

    def test_namespace_isolation(self):
        self.expert.ingest_quote(quote())
        other = StockExpert(self.path, 'other', clock=lambda: self.now)
        try:
            self.assertEqual(other.history('XNAS:EXAMPLE')['records'], [])
        finally:
            other.close()

    def test_immutable_rows(self):
        self.expert.ingest_quote(quote())
        with sqlite3.connect(self.path) as db:
            for sql in ('DELETE FROM events', "UPDATE events SET event_id='changed'"):
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute(sql)

    def test_bounded_history_and_notes(self):
        for i in range(3):
            self.expert.ingest_quote(quote(event_id=f'q-{i}'))
        result = self.expert.history('XNAS:EXAMPLE', limit=2)
        self.assertEqual(len(result['records']), 2)
        self.assertTrue(result['truncated'])
        for limit in (0, 1001, True):
            with self.assertRaises(ValueError):
                self.expert.history('XNAS:EXAMPLE', limit=limit)
        with self.assertRaises(ValueError):
            self.expert.remember_note('n', 'XNAS:EXAMPLE', 'x' * 4097, 'llm')

    def test_expert_has_auditable_paper_candidate(self):
        self.expert.ingest_quote(quote())
        decision = self.expert.evaluate('XNAS:EXAMPLE', size())
        self.assertEqual(decision['decision'], 'paper_candidate')
        self.assertEqual(decision['evidence_ids'], ['quote-1'])
        self.assertFalse(decision['executable'])
        self.assertEqual(decision['sizing']['quantity'], '9')

    def test_stale_delayed_adjusted_and_wrong_currency_fail_closed(self):
        for field, value, reason in (('feed', 'delayed', 'not_realtime'),
                                     ('adjustment', 'split', 'adjusted_price'),
                                     ('currency', 'EUR', 'currency_mismatch')):
            with self.subTest(field=field):
                self.expert.ingest_quote(quote(event_id=f'q-{field}', **{field: value}))
                self.assertIn(reason, self.expert.evaluate('XNAS:EXAMPLE', size())['blockers'])
        self.now += timedelta(seconds=61)
        self.assertIn('stale_quote', self.expert.evaluate('XNAS:EXAMPLE', size())['blockers'])

    def test_live_is_always_blocked_and_bad_inputs_fail(self):
        self.expert.ingest_quote(quote())
        self.assertIn('live_execution_unavailable', self.expert.evaluate('XNAS:EXAMPLE', size(), mode='live')['blockers'])
        self.assertIn('entry_price_mismatch', self.expert.evaluate('XNAS:EXAMPLE', size(entry='101'))['blockers'])
        with self.assertRaises(ValueError):
            self.expert.evaluate('XNAS:EXAMPLE', size(), max_age_seconds=True)

    def test_unknown_fields_and_cross_instrument_correction_rejected(self):
        self.expert.ingest_quote(quote())
        with self.assertRaises(ValueError):
            self.expert.ingest_quote(quote(event_id='bad', instrument='XNYS:OTHER', supersedes='quote-1'))
        with self.assertRaises(ValueError):
            self.expert.ingest_quote(quote(foo='ignored'))


if __name__ == '__main__':
    unittest.main()
