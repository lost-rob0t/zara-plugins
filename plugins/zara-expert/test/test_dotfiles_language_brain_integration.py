import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertHost
from zara_expert.language_family import register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.language_source_contract import validate_language_source_contracts


DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
FAMILY_KEYS = (
    "prolog",
    "python",
    "nim",
    "javascript",
    "typescript",
    "java",
    "kotlin",
)


@unittest.skipUnless(DOTFILES_ROOT, "canonical Dotfiles checkout not provided")
class DotfilesLanguageBrainIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.expert_root = cls.dotfiles_root / ".zara" / "experts"
        cls.sources = {
            key: [cls.expert_root / key / "kb" / "expert.pl"]
            for key in FAMILY_KEYS
        }
        for key, paths in cls.sources.items():
            for path in paths:
                if not path.is_file():
                    raise AssertionError(f"missing canonical {key} brain: {path}")
        validate_language_source_contracts(cls.sources)
        if not SwiplBackend.available():
            raise AssertionError("SWI-Prolog is required for canonical brain integration")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.host = ExpertHost(
            SwiplBackend(),
            state_root=Path(self.temporary.name) / "state",
            query_timeout_seconds=5.0,
        )
        registered = register_language_family(self.host, self.sources)
        self.assertEqual(registered, frozenset(FAMILY_KEYS))

    def tearDown(self):
        self.temporary.cleanup()

    def _assert_zero_model(self, outcome):
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])

    def _handler(self, key):
        return make_language_expert_handler(self.host, f"zara:expert/{key}")

    def _assert_applicable(self, key, path, expected):
        outcome = self._handler(key)(
            expert_operation="match",
            path=path,
            source_generation=f"generation-{key}-routing",
        )
        self._assert_zero_model(outcome)
        marker = f"applicable({'true' if expected else 'false'})"
        self.assertTrue(
            any(marker in item for item in outcome["data"]["result"]["evidence"]),
            outcome,
        )

    def _exercise_brain(self, key, path, source):
        expert_id = f"zara:expert/{key}"
        handler = make_language_expert_handler(self.host, expert_id)
        generation = f"generation-{key}-1"

        matched = handler(
            expert_operation="match",
            path=path,
            source_generation=generation,
        )
        self._assert_zero_model(matched)
        self.assertEqual(matched["verdict"], "succeeded")
        self.assertTrue(
            any("applicable(true)" in item for item in matched["data"]["result"]["evidence"])
        )

        inspected = handler(
            expert_operation="inspect",
            source=source,
            source_generation=generation,
        )
        self._assert_zero_model(inspected)
        self.assertTrue(
            any(
                "source_never_executed" in item
                for item in inspected["data"]["result"]["evidence"]
            )
        )

        diagnosed = handler(
            expert_operation="diagnose",
            source=source,
            source_generation=generation,
        )
        self._assert_zero_model(diagnosed)
        self.assertTrue(
            any(
                "fresh_evidence_required" in item
                for item in diagnosed["data"]["result"]["evidence"]
            )
        )

        preview = handler(
            expert_operation="repair.preview",
            source=source,
            source_generation=generation,
            diagnostic_ref=f"diagnostic:{key}:1",
        )
        self._assert_zero_model(preview)
        self.assertTrue(
            any("status(blocked)" in item for item in preview["data"]["result"]["evidence"])
        )

        verified = handler(
            expert_operation="repair.verify",
            original_source=source,
            candidate_source=f"{source} ",
            source_generation=f"generation-{key}-2",
        )
        self._assert_zero_model(verified)
        self.assertTrue(
            any("verified(false)" in item for item in verified["data"]["result"]["evidence"])
        )
        self.assertTrue(
            any(
                "fresh_postcondition_required" in item
                for item in verified["data"]["result"]["evidence"]
            )
        )

        styled = handler(
            expert_operation="style.rules",
            source=source,
            project_style=f"style:{key}:project",
        )
        self._assert_zero_model(styled)
        self.assertTrue(
            any("dotfiles_canonical_brain" in item for item in styled["data"]["result"]["evidence"])
        )

        explained = handler(
            expert_operation="explain",
            decision_ref=f"decision:{key}:1",
            source_generation=generation,
        )
        self._assert_zero_model(explained)
        self.assertTrue(
            any("provider_policy(disabled)" in item for item in explained["data"]["result"]["evidence"])
        )
        self.assertTrue(explained["data"]["result"]["explanation"])

        blocked = handler(
            expert_operation="repair.apply",
            repair="candidate-edit",
            expected_preimage=source,
            source_generation=generation,
        )
        self._assert_zero_model(blocked)
        self.assertEqual(blocked["verdict"], "blocked")
        self.assertEqual(blocked["data"]["reason"], "canonical-typed-edit-required")

    def test_real_dotfiles_brains_round_trip_through_registered_authority(self):
        cases = (
            ("prolog", "rules/main.pro", "fact(a)."),
            ("python", "src/main.pyi", "value: int"),
            ("nim", "pkg/tool.nimble", "discard"),
            ("javascript", "web/app.jsx", "export const App = () => null;"),
            ("typescript", "web/app.tsx", "export const value: number = 1;"),
            ("java", "android/src/Main.java", "final class Main {}"),
            ("kotlin", "android/src/Main.kt", "class Main"),
        )
        for key, path, source in cases:
            with self.subTest(expert=key):
                self._exercise_brain(key, path, source)

    def test_js_ts_and_java_kotlin_routing_stays_distinct(self):
        for path in ("app.js", "view.jsx", "worker.mjs", "legacy.cjs"):
            with self.subTest(expert="javascript", path=path):
                self._assert_applicable("javascript", path, True)
                self._assert_applicable("typescript", path, False)

        for path in ("app.ts", "view.tsx", "worker.mts", "legacy.cts"):
            with self.subTest(expert="typescript", path=path):
                self._assert_applicable("typescript", path, True)
                self._assert_applicable("javascript", path, False)

        with self.subTest(expert="java"):
            self._assert_applicable("java", "Main.java", True)
            self._assert_applicable("kotlin", "Main.java", False)

        for path in ("Main.kt", "build.gradle.kts"):
            with self.subTest(expert="kotlin", path=path):
                self._assert_applicable("kotlin", path, True)
                self._assert_applicable("java", path, False)

    def test_jvm_android_metadata_is_evidence_only(self):
        for key, source in (
            ("java", "final class Main {}"),
            ("kotlin", "class Main"),
        ):
            with self.subTest(expert=key):
                outcome = self._handler(key)(
                    expert_operation="inspect",
                    source=source,
                    source_generation=f"generation-{key}-metadata",
                )
                self._assert_zero_model(outcome)
                rendered = "\n".join(outcome["data"]["result"]["evidence"])
                self.assertIn("jvm_metadata", rendered)
                self.assertIn("android_metadata", rendered)
                self.assertNotIn("effect_receipt", rendered)


if __name__ == "__main__":
    unittest.main()
