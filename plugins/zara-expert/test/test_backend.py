import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import zara_expert.domain as expert_domain
from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertError, ExpertHost


class SwiplBackendTests(unittest.TestCase):
    def _program(self, directory: Path, body: str) -> Path:
        path = directory / "swipl"
        path.write_text(f"#!{sys.executable}\n" + body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    def _raw_request(self, root: Path, **overrides):
        request = {
            "namespace": "alpha",
            "operation": "query",
            "predicate": "thing",
            "arity": 1,
            "arguments": [{"var": "X"}],
            "knowledge_bases": (),
            "state_files": (str(root / "session.pl"), str(root / "persistent.pl")),
            "timeout_seconds": 0.5,
            "max_results": 3,
        }
        request.update(overrides)
        return request

    def _host(self, root: Path, program: Path, *, timeout=0.5, max_results=3):
        host = ExpertHost(
            SwiplBackend(str(program)),
            state_root=root / "state",
            query_timeout_seconds=timeout,
            max_results=max_results,
        )
        host.register("alpha", [], predicates={"thing": 1})
        return host

    def test_raw_backend_predicate_selection_is_not_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = SwiplBackend(str(root / "must-not-run"))
            with self.assertRaisesRegex(ExpertError, "registered predicate capability"):
                backend.run(self._raw_request(root, predicate="shell", arguments=["echo pwned"]))

    def test_forged_capability_descriptor_is_not_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = SwiplBackend(str(root / "must-not-run"))
            request = self._raw_request(root)
            request.pop("predicate")
            request.pop("arity")
            request["capability"] = {"predicate": "shell", "arity": 1}
            with self.assertRaisesRegex(ExpertError, "registered predicate capability"):
                backend.run(request)

    def test_imported_capability_factory_cannot_mint_backend_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = SwiplBackend(str(root / "must-not-run"))
            self.assertFalse(
                hasattr(expert_domain, "_issue_predicate_capability"),
                "generic same-process code must not be able to import a capability mint",
            )
            self.assertFalse(
                hasattr(expert_domain, "_CAPABILITY_ISSUER"),
                "generic same-process code must not be able to recover issuer authority",
            )
            self.assertFalse(
                hasattr(backend, "register_predicate") or hasattr(backend, "issue_capability"),
                "raw backend must not expose a replacement authority-minting API",
            )

    def test_registered_predicate_metadata_cannot_be_mutated_into_shell_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            host = self._host(root, root / "must-not-run")
            predicates = getattr(host, "_predicates", None)
            self.assertIsNone(
                predicates,
                "generic same-process code must not recover mutable callable predicate authority from the host",
            )

    def test_builds_registered_goal_and_limit_without_shell_interpolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            program = self._program(
                root,
                "import json, os\n"
                "print(json.dumps({'ok': True, 'results': [os.environ['ZARA_EXPERT_GOAL'], os.environ['ZARA_EXPERT_LIMIT']], 'trace': []}))\n",
            )
            result = self._host(root, program).query("alpha", "thing", [{"var": "X"}])
            self.assertEqual(result["results"], ["thing(X)", "3"])

    def test_argument_syntax_is_quoted_as_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            program = self._program(
                root,
                "import json, os\n"
                "print(json.dumps({'ok': True, 'results': [os.environ['ZARA_EXPERT_GOAL']], 'trace': []}))\n",
            )
            payload = "x),halt,thing(y"
            result = self._host(root, program).query("alpha", "thing", [payload])
            self.assertEqual(result["results"], ["thing('x),halt,thing(y')"])

    def test_explain_requests_trace_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            program = self._program(
                root,
                "import json, os\n"
                "print(json.dumps({'ok': True, 'results': [], 'trace': [os.environ['ZARA_EXPERT_EXPLAIN']]}))\n",
            )
            result = self._host(root, program).explain("alpha", "thing", [{"var": "X"}])
            self.assertEqual(result["trace"], ["1"])

    def test_timeout_kills_backend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            program = self._program(root, "import time\ntime.sleep(5)\n")
            with self.assertRaisesRegex(ExpertError, "timeout"):
                self._host(root, program, timeout=0.05).query("alpha", "thing", [{"var": "X"}])

    def test_nonzero_exit_fails_with_bounded_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            program = self._program(root, "import sys\nprint('backend broke', file=sys.stderr)\nsys.exit(7)\n")
            with self.assertRaisesRegex(ExpertError, "exit 7: backend broke"):
                self._host(root, program).query("alpha", "thing", [{"var": "X"}])

    def test_invalid_json_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            program = self._program(root, "print('not-json')\n")
            with self.assertRaisesRegex(ExpertError, "invalid structured output"):
                self._host(root, program).query("alpha", "thing", [{"var": "X"}])

    def test_boolean_output_limit_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "positive integer"):
            SwiplBackend(output_limit=True)

    def test_boolean_host_bounds_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = SwiplBackend(str(root / "must-not-run"))
            with self.assertRaisesRegex(ValueError, "finite positive"):
                ExpertHost(backend, state_root=root / "state", query_timeout_seconds=True)
            with self.assertRaisesRegex(ValueError, "positive integer"):
                ExpertHost(backend, state_root=root / "state", max_results=True)

    def test_forged_raw_arity_cannot_reach_backend(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = SwiplBackend(str(root / "must-not-run"))
            with self.assertRaisesRegex(ExpertError, "registered predicate capability"):
                backend.run(self._raw_request(root, arity=2))


if __name__ == "__main__":
    unittest.main()
