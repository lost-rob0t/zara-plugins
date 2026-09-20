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


class PrologRlmStyleOverlayResultIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.project = rule(
            "project_formatter",
            "project_global",
            preferred="nixfmt",
            project_id="workspace:style-runtime",
            project_generation=7,
            source=".zara/style/project.pl",
            revision="project-v1",
        )
        self.language = rule(
            "nix_formatter",
            "project_language",
            language="nix",
            project_id="workspace:style-runtime",
            project_generation=7,
            source=".zara/style/languages/nix.pl",
            revision="nix-v1",
        )
        self.fence = InvocationFence(
            workspace_id="workspace:style-runtime",
            workspace_generation=7,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace_id, generation: (
                workspace_id == "workspace:style-runtime" and generation == 7
            ),
        )

    def resolve(self, payload):
        return PrologRlmStyleOverlayAdapter(lambda _rules, _context: payload).resolve(
            [self.project, self.language],
            language="nix",
            known_languages=["nix", "bash"],
            budget=SharedSymbolicBudget(max_model_calls=0),
            fence=self.fence,
        )

    def test_effective_winner_must_match_exact_submitted_rule(self):
        forged_language = dict(self.language)
        forged_language["preferred"] = "forged-formatter"
        payload = resolved(self.project, forged_language)

        with self.assertRaisesRegex(CompositionError, "effective style rule was not submitted"):
            self.resolve(payload)

    def test_shadowed_provenance_must_match_submitted_rule(self):
        payload = resolved(self.project, self.language)
        payload["decisions"][0]["shadowed_provenance"][0] = {
            "id": self.project["id"],
            "scope": self.project["scope"],
            "revision": self.project["revision"],
            "provenance": {"source": "forged", "revision": self.project["revision"]},
        }

        with self.assertRaisesRegex(CompositionError, "style shadow provenance does not match submitted rule"):
            self.resolve(payload)

    def test_winner_scope_must_match_effective_rule(self):
        payload = resolved(self.project, self.language)
        payload["decisions"][0]["winner_scope"] = "session"

        with self.assertRaisesRegex(CompositionError, "style decision winner scope mismatch"):
            self.resolve(payload)


if __name__ == "__main__":
    unittest.main()
