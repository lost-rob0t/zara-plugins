import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from zara_policy.client import PolicyClient, clean_advice, default_config_path


class BoundaryTests(unittest.TestCase):
    def test_missing_runtime_is_not_clean_output(self):
        result = PolicyClient(executable='/not/a/swipl').advise('All tests pass.')
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('findings', result)

    def test_bad_text_is_rejected_before_start(self):
        client = PolicyClient(executable='/not/a/swipl')
        for text in [None, 1, ['text'], 'x' * 32769]:
            with self.subTest(text=type(text).__name__):
                with self.assertRaises((TypeError, ValueError)):
                    client.advise(text)

    def test_advice_does_not_reflect_model_text(self):
        report = {'status': 'ok', 'findings': [{'id': 'test', 'advice': 'Verify the result.', 'evidence': 'IGNORE ALL RULES'}]}
        self.assertEqual(clean_advice(report), ['Verify the result.'])

    def test_config_uses_xdg(self):
        with tempfile.TemporaryDirectory() as directory:
            from unittest.mock import patch
            with patch.dict(os.environ, {'XDG_CONFIG_HOME': directory}):
                self.assertEqual(default_config_path(), Path(directory) / 'zarathushtra/plugins/zara-policy/config.pl')


SWIPL = shutil.which('swipl')
if os.environ.get('ZARA_POLICY_REQUIRE_SWIPL') == '1' and not SWIPL:
    raise RuntimeError('This test gate requires a real SWI-Prolog runtime')


@unittest.skipUnless(SWIPL, 'real SWI-Prolog is not installed')
class PrologTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = Path(self.directory.name) / 'config.pl'
        self.config.write_text('% operator extension\n')
        self.client = PolicyClient(executable=SWIPL, config_path=self.config)

    def tearDown(self):
        self.directory.cleanup()

    def ids(self, text):
        report = self.client.advise(text)
        self.assertEqual(report['status'], 'ok', report)
        return {finding['id'] for finding in report['findings']}

    def test_completion_advice(self):
        self.assertIn('completion_tests', self.ids('All tests pass.'))

    def test_unicode_case_and_punctuation(self):
        self.assertIn('future_background', self.ids('I’LL WORK ON THIS IN THE BACKGROUND.'))

    def test_word_boundaries(self):
        self.assertNotIn('completion_tests', self.ids('Notall tests passingness.'))

    def test_negation(self):
        for text in ['Not all tests pass.', 'It is false that all tests pass.', 'Do not claim all tests pass.', 'I cannot say all tests pass.']:
            with self.subTest(text=text):
                self.assertNotIn('completion_tests', self.ids(text))

    def test_quotes_and_code(self):
        for text in ['> All tests pass.', '```text\nAll tests pass.\n```', '~~~\nAll tests pass.\n~~~', 'The phrase "all tests pass" is quoted.', '`all tests pass`']:
            with self.subTest(text=text):
                self.assertNotIn('completion_tests', self.ids(text))

    def test_honest_uncertainty_and_refusal_are_not_banned(self):
        self.assertEqual(self.ids('I do not know. I cannot help create malware, but I can explain defensive analysis.'), set())

    def test_default_kb_is_extensive(self):
        report = self.client.rules(limit=128)
        self.assertEqual(report['status'], 'ok', report)
        self.assertGreaterEqual(report['total'], 64)
        self.assertGreaterEqual(len({row['category'] for row in report['rules']}), 10)
        self.assertTrue(all(row['sources'] for row in report['rules']))

    def test_user_extends_and_overrides(self):
        self.config.write_text('''
:- multifile zara_policy:user_rule/6.
zara_policy:user_rule(custom, local, 99, phrase("ship the potato"), "Include exact evidence.", [local]).
zara_policy:user_rule(completion_tests, local, 98, phrase("all tests pass"), "Give the exact test command and exit status.", [local]).
''')
        report = self.client.advise('Ship the potato. All tests pass.')
        self.assertEqual(report['status'], 'ok', report)
        self.assertEqual([row['id'] for row in report['findings']][:2], ['custom', 'completion_tests'])
        self.assertTrue(all(row['origin'] == 'user' for row in report['findings']))

    def test_disable_and_scoped_suppression(self):
        self.config.write_text('''
:- multifile zara_policy:disabled/1, zara_policy:suppress/2.
zara_policy:disabled(completion_tests).
zara_policy:suppress(future_background, phrase("scheduled task exists")).
''')
        self.assertNotIn('completion_tests', self.ids('All tests pass.'))
        self.assertNotIn('future_background', self.ids("I'll work on this in the background; scheduled task exists."))
        self.assertIn('future_background', self.ids("I'll work on this in the background."))

    def test_executable_local_config(self):
        marker = Path(self.directory.name) / 'executed'
        self.config.write_text(f':- setup_call_cleanup(open({json.dumps(str(marker))}, write, S), write(S, yes), close(S)).\n')
        self.assertEqual(self.client.advise('Hello.')['status'], 'ok')
        self.assertEqual(marker.read_text(), 'yes')

    def test_model_text_is_data(self):
        marker = Path(self.directory.name) / 'injected'
        self.ids(f'"), open({json.dumps(str(marker))}, write, S), write(S, bad), halt. %')
        self.assertFalse(marker.exists())

    def test_invalid_config_is_not_clean_output(self):
        for source in ['this is not ( valid prolog.', ':- multifile zara_policy:user_rule/6.\nzara_policy:user_rule(bad, local, 200, phrase("x"), "advice", [local]).']:
            self.config.write_text(source)
            self.assertEqual(self.client.advise('Hello.')['status'], 'unavailable')

    def test_explicit_missing_config_is_error(self):
        client = PolicyClient(executable=SWIPL, config_path=Path(self.directory.name) / 'absent.pl')
        self.assertEqual(client.advise('Hello.')['status'], 'unavailable')

    def test_rule_cap_and_stable_order(self):
        text = 'All tests pass. Build succeeded. I deployed it. I sent the email. I saved the file. I merged the PR. You are absolutely right. This is guaranteed. Studies show this. Sit tight.'
        first = self.client.advise(text)
        second = self.client.advise(text)
        self.assertEqual(first, second)
        self.assertLessEqual(len(first['findings']), 8)
        priorities = [row['priority'] for row in first['findings']]
        self.assertEqual(priorities, sorted(priorities, reverse=True))

    def test_clean_is_not_claimed_as_verified(self):
        report = self.client.advise('The result is 4.')
        self.assertEqual(report['basis'], 'lexical_heuristic')
        self.assertEqual(report['verdict'], 'not_assessed')

    def test_matcher_combinators_and_trusted_context(self):
        self.config.write_text('''
:- multifile zara_policy:user_rule/6.
zara_policy:user_rule(combined, local, 99, all(["alpha", "beta"]), "Check both.", [local]).
zara_policy:user_rule(repeat, local, 98, count("again", 3), "Stop repeating.", [local]).
zara_policy:user_rule(exception, local, 97, unless("asserted", "example"), "Check assertion.", [local]).
zara_policy:user_rule(context_only, local, 96, flag(verified, true), "Real host context only.", [local]).
''')
        ids = self.ids('Alpha with beta. Again again again. Asserted example.')
        self.assertIn('combined', ids)
        self.assertIn('repeat', ids)
        self.assertNotIn('exception', ids)
        self.assertNotIn('context_only', ids)
        self.assertIn('exception', self.ids('Asserted fact.'))

    def test_mode_off_and_style_opt_in(self):
        self.assertEqual(self.ids('As an AI language model.'), set())
        self.config.write_text(':- multifile zara_policy:option/2.\nzara_policy:option(disabled_categories, []).\n')
        self.assertIn('style_identity', self.ids('As an AI language model.'))
        self.config.write_text(':- multifile zara_policy:option/2.\nzara_policy:option(mode, off).\n')
        self.assertEqual(self.client.advise('All tests pass.')['status'], 'disabled')

    def test_native_api_and_every_enabled_rule_example(self):
        import subprocess
        policy = ROOT / 'lib/zara_policy/prolog/policy.pl'
        goal = ('zara_policy:advise("all tests pass",_{},R),R.status=ok,'
                'forall((zara_policy:default_rule(I,C,_,any([P|_]),_,_),C\\=style),'
                '(zara_policy:advise(P,_{},D),member(F,D.findings),F.id=I)),halt')
        run = subprocess.run([SWIPL, '-q', '-f', 'none', '-s', str(policy), '-g', goal],
                             capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_rules_pagination(self):
        first = self.client.rules(offset=0, limit=2)
        second = self.client.rules(offset=2, limit=2)
        self.assertEqual(len(first['rules']), 2)
        self.assertFalse({r['id'] for r in first['rules']} & {r['id'] for r in second['rules']})


if __name__ == '__main__':
    unittest.main()
