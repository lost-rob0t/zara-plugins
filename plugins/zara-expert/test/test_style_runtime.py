import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import CompositionError, InvocationFence, SharedSymbolicBudget
from zara_expert.style_runtime import PrologRlmStyleOverlayAdapter


def rule(
    rule_id,
    scope,
    *,
    check="formatting.formatter",
    preferred="nixfmt-rfc-style",
    language="any",
    project_id="any",
    project_generation="any",
    revision="rev-1",
    source="fixture",
):
    return {
        "id": rule_id,
        "scope": scope,
        "language": language,
        "project_id": project_id,
        "project_generation": project_generation,
        "check": check,
        "preferred": preferred,
        "autofix": "none",
        "provenance": {"source": source, "revision": revision},
        "revision": revision,
        "overrides": [],
    }


class PrologRlmStyleOverlayAdapterTests(unittest.TestCase):
    def setUp(self):
        self.current_generation = 7
        self.cancelled = False

    def fence(self, generation=7):
        return InvocationFence(
            workspace_id="workspace:style-runtime",
            workspace_generation=generation,
            is_cancelled=lambda: self.cancelled,
            is_current_generation=lambda workspace_id, requested_generation: (
                workspace_id == "workspace:style-runtime"
                and requested_generation == self.current_generation
            ),
        )

    @staticmethod
    def resolved(project_rule, language_rule):
        return {
            "effective": [language_rule],
            "decisions": [
                {
                    "check": language_rule["check"],
                    "winner": language_rule["id"],
                    "winner_scope": language_rule["scope"],
                    "winner_revision": language_rule["revision"],
                    "winner_provenance": language_rule["provenance"],
                    "shadowed": [project_rule["id"]],
                    "shadowed_provenance": [
                        {
                            "id": project_rule["id"],
                            "scope": project_rule["scope"],
                            "revision": project_rule["revision"],
                            "provenance": project_rule["provenance"],
                        }
                    ],
                }
            ],
            "project_id": "workspace:style-runtime",
            "project_generation": 7,
            "language": "nix",
            "usage": {"model_calls": 0},
        }

    def test_binds_workspace_zero_model_context_and_retains_shadow_provenance(self):
        project = rule(
            "project_formatter",
            "project_global",
            preferred="nixfmt",
            project_id="workspace:style-runtime",
            project_generation=7,
            source=".zara/style/project.pl",
            revision="project-v1",
        )
        language = rule(
            "nix_formatter",
            "project_language",
            language="nix",
            project_id="workspace:style-runtime",
            project_generation=7,
            source=".zara/style/languages/nix.pl",
            revision="nix-v1",
        )
        calls = []

        def resolver(rules, context):
            calls.append((rules, context))
            return self.resolved(project, language)

        budget = SharedSymbolicBudget(max_model_calls=0)
        result = PrologRlmStyleOverlayAdapter(resolver).resolve(
            [project, language],
            language="nix",
            known_languages=["nix", "bash"],
            budget=budget,
            fence=self.fence(),
        )

        self.assertEqual(
            calls[0][1],
            {
                "project_id": "workspace:style-runtime",
                "project_generation": 7,
                "language": "nix",
                "known_languages": ["nix", "bash"],
                "max_model_calls": 0,
            },
        )
        self.assertEqual(result.effective[0]["id"], "nix_formatter")
        self.assertEqual(
            result.evidence,
            (
                "style:formatting.formatter:winner:nix_formatter@nix-v1",
                "style:formatting.formatter:shadowed:project_formatter@project-v1",
            ),
        )
        self.assertIn("style_overlay_resolve/3", result.explanation)
        self.assertIn("winning and shadowed provenance retained", result.explanation)
        self.assertEqual(budget.max_model_calls, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_nonzero_upstream_usage_fails_closed(self):
        project = rule(
            "project_formatter",
            "project_global",
            project_id="workspace:style-runtime",
            project_generation=7,
        )
        language = rule(
            "nix_formatter",
            "project_language",
            language="nix",
            project_id="workspace:style-runtime",
            project_generation=7,
        )
        payload = self.resolved(project, language)
        payload["usage"] = {"model_calls": 1}
        adapter = PrologRlmStyleOverlayAdapter(lambda _rules, _context: payload)
        with self.assertRaisesRegex(CompositionError, "attempted model use"):
            adapter.resolve(
                [project, language],
                language="nix",
                known_languages=["nix"],
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self.fence(),
            )

    def test_generation_change_after_upstream_completion_rejects_late_result(self):
        project = rule(
            "project_formatter",
            "project_global",
            project_id="workspace:style-runtime",
            project_generation=7,
        )
        language = rule(
            "nix_formatter",
            "project_language",
            language="nix",
            project_id="workspace:style-runtime",
            project_generation=7,
        )

        def resolver(_rules, _context):
            self.current_generation = 8
            return self.resolved(project, language)

        with self.assertRaisesRegex(CompositionError, "stale workspace generation"):
            PrologRlmStyleOverlayAdapter(resolver).resolve(
                [project, language],
                language="nix",
                known_languages=["nix"],
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self.fence(),
            )

    def test_cancelled_request_never_reaches_upstream_resolver(self):
        called = False

        def resolver(_rules, _context):
            nonlocal called
            called = True
            raise AssertionError("cancelled style request must not dispatch")

        self.cancelled = True
        with self.assertRaisesRegex(CompositionError, "expert invocation cancelled"):
            PrologRlmStyleOverlayAdapter(resolver).resolve(
                [],
                language="nix",
                known_languages=["nix"],
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self.fence(),
            )
        self.assertFalse(called)

    def test_result_shape_or_provenance_drift_fails_closed(self):
        project = rule(
            "project_formatter",
            "project_global",
            project_id="workspace:style-runtime",
            project_generation=7,
        )
        language = rule(
            "nix_formatter",
            "project_language",
            language="nix",
            project_id="workspace:style-runtime",
            project_generation=7,
        )
        payload = self.resolved(project, language)
        payload["authority"] = ["network"]
        with self.assertRaisesRegex(CompositionError, "result shape drifted"):
            PrologRlmStyleOverlayAdapter(lambda _rules, _context: payload).resolve(
                [project, language],
                language="nix",
                known_languages=["nix"],
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self.fence(),
            )

        payload = self.resolved(project, language)
        payload["decisions"][0]["winner_revision"] = "forged-revision"
        with self.assertRaisesRegex(CompositionError, "winner revision mismatch"):
            PrologRlmStyleOverlayAdapter(lambda _rules, _context: payload).resolve(
                [project, language],
                language="nix",
                known_languages=["nix"],
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self.fence(),
            )

    def test_rules_and_language_contract_are_closed_before_dispatch(self):
        called = False

        def resolver(_rules, _context):
            nonlocal called
            called = True
            raise AssertionError("invalid style request must not dispatch")

        adapter = PrologRlmStyleOverlayAdapter(resolver)
        bad = rule("bad", "library_default")
        bad["capabilities"] = ["network"]
        with self.assertRaisesRegex(CompositionError, "does not match upstream contract"):
            adapter.resolve(
                [bad],
                language="nix",
                known_languages=["nix"],
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self.fence(),
            )
        with self.assertRaisesRegex(CompositionError, "language is not known"):
            adapter.resolve(
                [],
                language="nix",
                known_languages=["bash"],
                budget=SharedSymbolicBudget(max_model_calls=0),
                fence=self.fence(),
            )
        self.assertFalse(called)


if __name__ == "__main__":
    unittest.main()
