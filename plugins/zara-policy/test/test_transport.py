from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'lib'))
from zara_policy.client import PolicyClient, _exchange, clean_advice, MAX_RESPONSE_BYTES, MAX_STDERR_BYTES


class TransportTests(unittest.TestCase):
    def test_process_roundtrip(self):
        payload = b'{"message":"hello"}\n'
        self.assertEqual(_exchange([sys.executable, '-c', 'import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())'], payload, 2), payload)

    def test_stalled_process_is_killed(self):
        start = time.monotonic()
        with self.assertRaises(TimeoutError):
            _exchange([sys.executable, '-c', 'import time; time.sleep(30)'], b'{}\n', .1)
        self.assertLess(time.monotonic() - start, 3)

    def test_stdout_and_stderr_are_bounded(self):
        for stream, maximum in [('stdout', MAX_RESPONSE_BYTES), ('stderr', MAX_STDERR_BYTES)]:
            with self.subTest(stream=stream), self.assertRaises(ValueError):
                _exchange([sys.executable, '-c', f'import sys; sys.{stream}.write("x"*{maximum+10000})'], b'{}\n', 2)

    def test_nonzero_exit_is_not_success(self):
        with self.assertRaises(RuntimeError):
            _exchange([sys.executable, '-c', 'raise SystemExit(7)'], b'{}\n', 2)

    def test_invalid_and_oversize_response(self):
        client = PolicyClient(executable=sys.executable)
        for response in [b'not json', b'[]', b'{"status":"ok","findings":{}}', b'{"status":"ok","findings":[1]}']:
            with patch('zara_policy.client._exchange', return_value=response):
                self.assertEqual(client.advise('text')['status'], 'unavailable')

    def test_malformed_advice_does_not_crash(self):
        for findings in [None, 2, {}, ['hostile', {}, {'advice': 42}]]:
            self.assertEqual(clean_advice({'status':'ok','findings':findings}), [])

    def test_timeout_and_no_raw_errors(self):
        client = PolicyClient(executable=sys.executable)
        with patch('zara_policy.client._exchange', side_effect=TimeoutError('secret')):
            self.assertEqual(client.advise('text')['reason'], 'timeout')
        with patch('zara_policy.client._exchange', side_effect=OSError('secret')):
            self.assertNotIn('secret', str(client.advise('text')))

    def test_invalid_options(self):
        for timeout in [False, float('nan'), 0, 11]:
            with self.assertRaises(ValueError):
                PolicyClient(timeout=timeout)
        for offset, limit in [(True, 1), (-1, 1), (0, 129), (0, False)]:
            with self.assertRaises(ValueError):
                PolicyClient().rules(offset=offset, limit=limit)

    def test_missing_and_oversized_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.pl'
            client = PolicyClient(executable=sys.executable, config_path=path)
            self.assertEqual(client.advise('text')['reason'], 'invalid_config_file')
            path.write_text('x' * 131073)
            self.assertEqual(client.advise('text')['reason'], 'invalid_config_file')

    def test_busy_does_not_start_another_process(self):
        import zara_policy.client as module
        self.assertTrue(module._PROCESS_SLOTS.acquire(False))
        self.assertTrue(module._PROCESS_SLOTS.acquire(False))
        try:
            self.assertEqual(PolicyClient(executable=sys.executable).advise('text')['reason'], 'busy')
        finally:
            module._PROCESS_SLOTS.release()
            module._PROCESS_SLOTS.release()
