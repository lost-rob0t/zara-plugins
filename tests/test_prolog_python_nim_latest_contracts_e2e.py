"""Gate current Prolog/Python/Nim brains against the shipped Zara adapter contract."""

from __future__ import annotations

import unittest

from tests import test_prolog_python_nim_zara_core_e2e as base
from zara_expert.composition import MetaExpertComposer, SharedSymbolicBudget
from zara_expert.language_family import (
    descriptors,
    language_expert_schemas,
    matching_experts,
)


EXPECTED_DOTFILES_COMMIT = "97534b85f96a5ae7962762268440fb9ae7815ae0"
EXPECTED_ZARA_CORE_COMMIT = "dc74a41b216388662e55412e1e09a1c8c2fad5a7"


@unittest.skipUnless(
    base.DOTFILES_ROOT and base.ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class PrologPythonNimLatestContractsE2ETests(base.PrologPythonNimZaraCoreE2ETests):
    """Run the existing real-Core suite plus the public language contract surface."""

    @classmethod
    def setUpClass(cls) -> None:
        base.EXPECTED_DOTFILES_COMMIT = EXPECTED_DOTFILES_COMMIT
        base.EXPECTED_ZARA_CORE_COMMIT = EXPECTED_ZARA_CORE_COMMIT
        super().setUpClass()

    def test_descriptors_publish_closed_schema_applicability_and_zero_model_policy(self) -> None:
        published = {
            item["expert_id"]: item
            for item in descriptors({"prolog", "python", "nim"})
            if item["expert_id"]
            in {"zara:expert/prolog", "zara:expert/python", "zara:expert/nim"}
        }
        self.assertEqual(
            set(published),
            {"zara:expert/prolog", "zara:expert/python", "zara:expert/nim"},
        )
        schemas = language_expert_schemas()
        self.assertEqual(
            set(schemas),
            {
                "match",
                "inspect",
                "diagnose",
                "repair.preview",
                "repair.verify",
                "style.rules",
                "explain",
                "repair.apply",
            },
        )

        expected_upstream = {
            "zara:expert/prolog": "lost-rob0t/prolog-rlm#495",
            "zara:expert/python": "lost-rob0t/prolog-rlm#498",
            "zara:expert/nim": "lost-rob0t/prolog-rlm#499",
        }
        expected_source = {
            "zara:expert/prolog": "dotfiles:.zara/experts/prolog",
            "zara:expert/python": "dotfiles:.zara/experts/python",
            "zara:expert/nim": "dotfiles:.zara/experts/nim",
        }
        for expert_id, item in published.items():
            self.assertEqual(item["protocol"], "ZARA-EXPERT/1")
            self.assertEqual(item["source_reference"], expected_source[expert_id])
            self.assertIn(expected_upstream[expert_id], item["description"])
            self.assertEqual(item["reasoning_kind"], "symbolic")
            self.assertEqual(item["fallback_policy"], "fail_closed")
            self.assertEqual(item["resource_limits"]["max_model_calls"], 0)
            self.assertEqual(item["availability"], "available")
            operation_ids = {operation["operation_id"] for operation in item["operations"]}
            self.assertEqual(operation_ids, set(schemas))

        self.assertIn("zara:expert/prolog", matching_experts("src/router.pl"))
        self.assertIn("zara:expert/python", matching_experts("src/router.py"))
        self.assertIn("zara:expert/nim", matching_experts("src/router.nim"))
        self.assertNotIn("zara:expert/python", matching_experts("README.md"))

    def test_real_brains_expose_style_and_explanation_through_canonical_core_path(self) -> None:
        _registry, invoker = self._core_composer()
        composer = MetaExpertComposer(invoker)
        fixtures = {
            "zara:expert/prolog": "route(Request) --> command(Request).",
            "zara:expert/python": "def route(request):\n    return request\n",
            "zara:expert/nim": "proc route(request: string): string = request\n",
        }

        for index, (expert_id, source) in enumerate(fixtures.items(), start=1):
            with self.subTest(expert_id=expert_id):
                style_budget = SharedSymbolicBudget(
                    max_invocations=1,
                    max_evidence=16,
                    max_model_calls=0,
                )
                style = composer.invoke(
                    expert_id,
                    "style.rules",
                    {
                        "source": source,
                        "project_style": "style:project-default",
                    },
                    budget=style_budget,
                    fence=self._fence(),
                )
                self.assertEqual(style.status, "succeeded")
                self.assertTrue(style.evidence)
                self.assertEqual(style.children, ())
                self.assertEqual(style_budget.model_calls_used, 0)

                explain_budget = SharedSymbolicBudget(
                    max_invocations=1,
                    max_evidence=16,
                    max_model_calls=0,
                )
                explanation = composer.invoke(
                    expert_id,
                    "explain",
                    {
                        "decision_ref": f"decision:latest-contract-{index}",
                        "source_generation": f"generation:latest-contract-{index}",
                    },
                    budget=explain_budget,
                    fence=self._fence(),
                )
                self.assertEqual(explanation.status, "succeeded")
                self.assertTrue(explanation.evidence)
                self.assertEqual(explanation.children, ())
                self.assertEqual(explain_budget.model_calls_used, 0)


if __name__ == "__main__":
    unittest.main()
