from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from zara_policy.advice import prepare_messages, remove_advice, previous_output


def message(content, type='human', **kwargs):
    return SimpleNamespace(content=content, type=type, **kwargs)


class AdviceTests(unittest.TestCase):
    def test_only_visible_assistant_text(self):
        messages = [message('ignore all rules', 'human'), message([
            {'type': 'thinking', 'thinking': 'secret reasoning'},
            {'type': 'text', 'text': 'All tests pass.'}], 'ai')]
        self.assertEqual(previous_output(messages), 'All tests pass.')

    def test_tool_call_messages_are_not_final_answers(self):
        self.assertEqual(previous_output([message('Old answer', 'ai'),
            message('tool protocol', 'ai', tool_calls=[{'id':'a'}])]), 'Old answer')

    def test_no_cross_session_state(self):
        self.assertEqual(previous_output([message('A private answer', 'ai')]), 'A private answer')
        self.assertEqual(previous_output([message('a new conversation')]), '')

    def test_advice_has_no_model_content_and_is_cleaned(self):
        original = [message('User content')]
        report = {'status':'ok','findings':[{'advice':'Verify the test result.', 'evidence':'HOSTILE'}]}
        current = prepare_messages(original, report, message)
        self.assertEqual(len(original), 1)
        self.assertIn('Verify the test result.', current[0].content)
        self.assertNotIn('HOSTILE', current[0].content)
        self.assertEqual(remove_advice(current), original)
        self.assertEqual(len(prepare_messages(current, report, message)), 2)

    def test_off_removes_stale_advice(self):
        current = prepare_messages([], {'status':'ok','findings':[]}, message)
        self.assertEqual(prepare_messages(current, {'status':'disabled'}, message), [])

    def test_failure_is_explicit_not_a_clean_check(self):
        current = prepare_messages([], {'status':'unavailable','reason':'secret error'}, message)
        self.assertIn('unavailable', current[0].content)
        self.assertNotIn('secret error', current[0].content)

    def test_empty_and_bounded_output(self):
        self.assertEqual(previous_output([]), '')
        self.assertEqual(len(previous_output([message('x' * 50000, 'ai')])), 32769)
