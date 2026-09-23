import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertError


class CorePredicateExecutorTests(unittest.TestCase):
    def _program(self, directory: Path) -> Path:
        path = directory / "swipl"
        path.write_text(
            f"#!{sys.executable}\n"
            "import json, os\n"
            "print(json.dumps({"
            "'ok': True,"
            "'results': [os.environ['ZARA_EXPERT_GOAL'], os.environ['ZARA_EXPERT_LIMIT']],"
            "'trace': [os.environ['ZARA_EXPERT_EXPLAIN']]"
            "}))\n",
            encoding="utf-8",
        )
        path.chmod(path.stat().st_mode | stat.S_IXUSR)
        return path

    @staticmethod
    def _binding(**overrides):
        values = {
            "namespace": "alpha",
            "predicate": "thing",
            "arity": 1,
            "generation": 7,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_core_binding_executes_exact_registered_predicate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = SwiplBackend(str(self._program(root)))
            result = backend.run_core_binding(
                self._binding(),
                operation="query",
                arguments=[{"var": "X"}],
                knowledge_bases=(),
                state_files=(),
                timeout_seconds=0.5,
                max_results=3,
            )
            self.assertEqual(result["results"], ["thing(X)", "3"])
            self.assertEqual(result["trace"], ["0"])

    def test_core_binding_explain_uses_same_exact_predicate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            backend = SwiplBackend(str(self._program(root)))
            result = backend.run_core_binding(
                self._binding(),
                operation="explain",
                arguments=["literal"],
                knowledge_bases=(),
                state_files=(),
                timeout_seconds=0.5,
                max_results=2,
            )
            self.assertEqual(result["results"], ["thing('literal')", "2"])
            self.assertEqual(result["trace"], ["1"])

    def test_core_binding_rejects_arity_mismatch_before_process_start(self):
        backend = SwiplBackend("must-not-run")
        with self.assertRaisesRegex(ExpertError, "arity mismatch"):
            backend.run_core_binding(
                self._binding(arity=2),
                operation="query",
                arguments=["one"],
                knowledge_bases=(),
                state_files=(),
                timeout_seconds=0.5,
                max_results=3,
            )

    def test_core_binding_rejects_noncanonical_binding_identity(self):
        backend = SwiplBackend("must-not-run")
        for binding in (
            self._binding(namespace="user:alpha"),
            self._binding(predicate="shell/1"),
            self._binding(predicate="thing(X)"),
            self._binding(arity=True),
        ):
            with self.subTest(binding=binding):
                with self.assertRaises(ExpertError):
                    backend.run_core_binding(
                        binding,
                        operation="query",
                        arguments=["x"],
                        knowledge_bases=(),
                        state_files=(),
                        timeout_seconds=0.5,
                        max_results=3,
                    )

    def test_core_binding_rejects_unknown_operation(self):
        backend = SwiplBackend("must-not-run")
        with self.assertRaisesRegex(ExpertError, "unsupported expert operation"):
            backend.run_core_binding(
                self._binding(),
                operation="shell",
                arguments=["x"],
                knowledge_bases=(),
                state_files=(),
                timeout_seconds=0.5,
                max_results=3,
            )


if __name__ == "__main__":
    unittest.main()
