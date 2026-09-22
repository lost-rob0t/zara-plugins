import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.composition import (
    CompositionError,
    InvocationFence,
    MetaExpertComposer,
    SharedSymbolicBudget,
)
from zara_expert.dotfiles_style_expert import (
    STYLE_EXPERT_ID,
    DotfilesStyleCompositionInvoker,
)


def _hex_json(payload):
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return "".join(f"{ord(char):06x}" for char in text)


class _TextSubclass(str):
    pass


class FakeStyleExpertHost:
    def __init__(self, rule):
        self.rule = rule
        self.calls = []

    def query(self, namespace, predicate, arguments):
        self.calls.append((namespace, predicate, list(arguments)))
        if predicate == "style_policy":
            return {
                "ok": True,
                "results": ["style_policy(disabled,0,0)"],
                "trace": [],
            }
        if predicate == "style_rules_json_hex":
            project_id, generation, language = arguments[:3]
            payload = {
                "project_id": project_id,
                "project_generation": generation,
                "language": language,
                "rules": [self.rule],
            }
            return {
                "ok": True,
                "results": [
                    f"style_rules_json_hex('{project_id}',{generation},{language},{_hex_json(payload)})"
                ],
                "trace": [],
            }
        raise AssertionError(f"unexpected predicate: {predicate}")


def _resolver(rules, context):
    rule = rules[0]
    return {
        "effective": [rule],
        "decisions": [
            {
                "check": rule["check"],
                "winner": rule["id"],
                "winner_scope": rule["scope"],
                "winner_revision": rule["revision"],
                "winner_provenance": rule["provenance"],
                "shadowed": [],
                "shadowed_provenance": [],
            }
        ],
        "project_id": context["project_id"],
        "project_generation": context["project_generation"],
        "language": context["language"],
        "usage": {"model_calls": 0},
    }


class DotfilesStyleMetaCompositionTests(unittest.TestCase):
    def setUp(self):
        self.rule = {
            "id": "dotfiles.nix.formatting.formatter",
            "scope": "project_language",
            "language": "nix",
            "project_id": "workspace:meta-style",
            "project_generation": 11,
            "check": "formatting.formatter",
            "preferred": "nixfmt-rfc-style",
            "autofix": "none",
            "provenance": {
                "source": ".prolog/kb/literate_sync.pl",
                "kind": "durable_kb",
                "scope": "project_language",
            },
            "revision": "dotfiles-nix-style-v1",
            "overrides": [],
        }
        self.host = FakeStyleExpertHost(self.rule)
        self.fence = InvocationFence(
            workspace_id="workspace:meta-style",
            workspace_generation=11,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace_id, generation: (
                workspace_id == "workspace:meta-style" and generation == 11
            ),
        )

    def _composer(self):
        return MetaExpertComposer(
            DotfilesStyleCompositionInvoker(self.host, resolver=_resolver)
        )

    def test_meta_composer_owns_style_evidence_accounting_exactly_once(self):
        budget = SharedSymbolicBudget(max_evidence=5, max_model_calls=0)
        node = self._composer().invoke(
            STYLE_EXPERT_ID,
            "resolve",
            {"language": "nix"},
            budget=budget,
            fence=self.fence,
        )

        self.assertEqual(node.status, "succeeded")
        self.assertEqual(node.data["language"], "nix")
        self.assertEqual(node.data["effective"], [self.rule])
        self.assertEqual(len(node.evidence), 5)
        self.assertEqual(budget.evidence_used, len(node.evidence))
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.model_calls_used, 0)
        self.assertIn("Dotfiles StyleExpert", node.explanation)
        self.assertEqual(len(self.host.calls), 2)

    def test_meta_composer_rejects_style_evidence_over_budget_without_double_charge(self):
        budget = SharedSymbolicBudget(max_evidence=4, max_model_calls=0)

        with self.assertRaisesRegex(CompositionError, "expert evidence budget exceeded"):
            self._composer().invoke(
                STYLE_EXPERT_ID,
                "resolve",
                {"language": "nix"},
                budget=budget,
                fence=self.fence,
            )

        self.assertEqual(budget.evidence_used, 0)
        self.assertEqual(budget.invocations_used, 1)
        self.assertEqual(budget.model_calls_used, 0)
        self.assertEqual(len(self.host.calls), 2)

    def test_style_invoker_rejects_noncanonical_operation_before_host_dispatch(self):
        budget = SharedSymbolicBudget(max_model_calls=0)

        with self.assertRaisesRegex(CompositionError, "unsupported StyleExpert operation"):
            self._composer().invoke(
                STYLE_EXPERT_ID,
                "repair.apply",
                {"language": "nix"},
                budget=budget,
                fence=self.fence,
            )

        self.assertEqual(self.host.calls, [])
        self.assertEqual(budget.evidence_used, 0)
        self.assertEqual(budget.model_calls_used, 0)

    def test_style_invoker_rejects_noncanonical_route_text_before_host_dispatch(self):
        cases = (
            (
                _TextSubclass(STYLE_EXPERT_ID),
                "resolve",
                {"language": "nix"},
                "unsupported StyleExpert identity",
            ),
            (
                STYLE_EXPERT_ID,
                _TextSubclass("resolve"),
                {"language": "nix"},
                "unsupported StyleExpert operation",
            ),
            (
                STYLE_EXPERT_ID,
                "resolve",
                {"language": _TextSubclass("nix")},
                "language must be exact text",
            ),
        )
        for expert_id, operation, input_data, message in cases:
            with self.subTest(expert_id=expert_id, operation=operation, input_data=input_data):
                budget = SharedSymbolicBudget(max_model_calls=0)
                with self.assertRaisesRegex(CompositionError, message):
                    self._composer().invoke(
                        expert_id,
                        operation,
                        input_data,
                        budget=budget,
                        fence=self.fence,
                    )
                self.assertEqual(self.host.calls, [])
                self.assertEqual(budget.evidence_used, 0)
                self.assertEqual(budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
