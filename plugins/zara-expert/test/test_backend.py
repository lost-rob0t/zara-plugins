import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertError


class SwiplBackendTests(unittest.TestCase):
    def _program(self, directory: Path, body: str) -> Path:
        path = directory / "swipl"
        path.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def _request(self, root: Path, **overrides):
        request = {
            "namespace": "alpha",
            "operation": "query",
            "goal": "thing(X)",
            "knowledge_bases": (),
            "state_files": (str(root / "session.pl"), str(root / "persistent.pl")),
            "timeout_seconds": 0.5,
            "max_results": 3,
        }
        request.update(overrides)
        return request

    def test_forwards_goal_and_limit_without_shell_interpolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            program = self._program(
                root,
                "import json, os\n"
                "print(json.dumps({'ok': True, 'results': [os.environ['ZARA_EXPERT_GOAL'], os.environ['ZARA_EXPERT_LIMIT']], 'trace': []}))\n",
            )
            result = SwiplBackend(str(program)).run(self._request(root))
            self.assertEqual(result["results"], ["thing(X)", "3"])

    def test_explain_requests_trace_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            program = self._program(
                root,
                "import json, os\n"
                "print(json.dumps({'ok': True, 'results': [], 'trace': [os.environ['ZARA_EXPERT_EXPLAIN']]}))\n",
            )
            result = SwiplBackend(str(program)).run(self._request(root, operation="explain"))
            self.assertEqual(result["trace"], ["1"])

    def test_timeout_kills_backend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            program = self._program(root, "import time\ntime.sleep(5)\n")
            with self.assertRaisesRegex(ExpertError, "timeout"):
                SwiplBackend(str(program)).run(self._request(root, timeout_seconds=0.05))

    def test_nonzero_exit_fails_with_bounded_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            program = self._program(root, "import sys\nprint('backend broke', file=sys.stderr)\nsys.exit(7)\n")
            with self.assertRaisesRegex(ExpertError, "exit 7: backend broke"):
                SwiplBackend(str(program)).run(self._request(root))

    def test_invalid_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            program = self._program(root, "print('not-json')\n")
            with self.assertRaisesRegex(ExpertError, "invalid structured output"):
                SwiplBackend(str(program)).run(self._request(root))


if __name__ == "__main__":
    unittest.main()
