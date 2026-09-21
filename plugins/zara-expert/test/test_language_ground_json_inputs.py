import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost
from zara_expert.language_handler import make_language_expert_handler


class NeverRunBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        raise AssertionError("invalid repair payload reached registered predicate backend")


class LanguageGroundJsonInputTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.backend = NeverRunBackend()
        self.host = ExpertHost(
            self.backend,
            state_root=Path(self.temporary.name) / "state",
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _repair_apply(self, expert_id, repair):
        handler = make_language_expert_handler(self.host, expert_id)
        return handler(
            expert_operation="repair.apply",
            repair=repair,
            expected_preimage="sha256:fixture",
            source_generation="generation:fixture",
        )

    def test_lane3_repair_objects_require_ground_json_before_effect_boundary(self):
        cycle = {"kind": "replace"}
        cycle["self"] = cycle
        invalid_repairs = (
            {1: "non-string-key"},
            {"score": math.nan},
            {"score": math.inf},
            {"score": -math.inf},
            {"payload": b"bytes-are-not-json"},
            {"payload": {"set-value"}},
            {"var": "Injected"},
            {"edit": [{"var": "InjectedNested"}]},
            cycle,
        )

        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            for repair in invalid_repairs:
                with self.subTest(expert_id=expert_id, repair=repr(repair)[:120]):
                    with self.assertRaisesRegex(
                        ExpertError,
                        "invalid input field value",
                    ):
                        self._repair_apply(expert_id, repair)

        self.assertEqual(self.backend.calls, [])

    def test_lane3_valid_ground_json_repair_stays_blocked_without_effect(self):
        repair = {
            "kind": "replace",
            "range": {"start": 3, "end": 9},
            "text": "fact(ok).",
            "metadata": {
                "confidence": 0.875,
                "tags": ["symbolic", None, True, 7],
            },
        }

        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            with self.subTest(expert_id=expert_id):
                outcome = self._repair_apply(expert_id, repair)
                self.assertEqual(outcome["verdict"], "blocked")
                self.assertEqual(outcome["usage"], {"model_calls": 0})
                self.assertEqual(outcome["effect_receipts"], [])
                self.assertEqual(
                    outcome["data"]["reason"],
                    "canonical-typed-edit-required",
                )

        self.assertEqual(self.backend.calls, [])


if __name__ == "__main__":
    unittest.main()
