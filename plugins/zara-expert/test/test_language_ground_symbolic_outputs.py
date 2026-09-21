import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost
from zara_expert.language_family import register_language_family
from zara_expert.language_handler import make_language_expert_handler


class StaticBackend:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return self.result


class LanguageGroundSymbolicOutputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def _brain(self, key):
        path = self.root / f"{key}.pl"
        path.write_text("% ground-symbolic-output-fixture\n", encoding="utf-8")
        return path

    def _handler(self, key, result):
        backend = StaticBackend(result)
        host = ExpertHost(backend, state_root=self.root / f"state-{key}-{id(backend)}")
        register_language_family(host, {key: [self._brain(f"{key}-{id(backend)}")]})
        return backend, make_language_expert_handler(host, f"zara:expert/{key}")

    def test_lane3_non_string_symbolic_evidence_never_becomes_replayable_output(self):
        invalid_evidence = (
            {"legacy": "opaque-result"},
            ["nested", "legacy"],
            {"var": "InjectedResult"},
            None,
            7,
        )

        for key in ("prolog", "python", "nim"):
            for bad in invalid_evidence:
                with self.subTest(expert=key, evidence=repr(bad)):
                    backend, handler = self._handler(
                        key,
                        {
                            "ok": True,
                            "results": [bad],
                            "trace": ["rule(symbolic)"],
                        },
                    )
                    with self.assertRaisesRegex(ExpertError, "malformed expert evidence"):
                        handler(
                            expert_operation="inspect",
                            source="symbolic source",
                            source_generation="generation:ground-output",
                        )
                    self.assertEqual(len(backend.calls), 1)

    def test_lane3_non_string_explanation_trace_never_becomes_replayable_output(self):
        for key in ("prolog", "python", "nim"):
            with self.subTest(expert=key):
                backend, handler = self._handler(
                    key,
                    {
                        "ok": True,
                        "results": ["evidence(symbolic)"],
                        "trace": [{"legacy": "opaque-trace"}],
                    },
                )
                with self.assertRaisesRegex(ExpertError, "malformed expert explanation"):
                    handler(
                        expert_operation="explain",
                        decision_ref="decision:ground-output",
                        source_generation="generation:ground-output",
                    )
                self.assertEqual(len(backend.calls), 1)

    def test_lane3_string_only_symbolic_output_preserves_zero_model_effect_contract(self):
        for key in ("prolog", "python", "nim"):
            with self.subTest(expert=key):
                _backend, handler = self._handler(
                    key,
                    {
                        "ok": True,
                        "results": ["evidence(symbolic)"],
                        "trace": ["rule(symbolic)"],
                    },
                )
                outcome = handler(
                    expert_operation="explain",
                    decision_ref="decision:ground-output-valid",
                    source_generation="generation:ground-output-valid",
                )
                self.assertEqual(outcome["verdict"], "succeeded")
                self.assertEqual(outcome["usage"], {"model_calls": 0})
                self.assertEqual(outcome["effect_receipts"], [])
                self.assertEqual(
                    outcome["data"]["explanation"],
                    {
                        "symbolic_terms": ["evidence(symbolic)"],
                        "trace": ["rule(symbolic)"],
                    },
                )


if __name__ == "__main__":
    unittest.main()
