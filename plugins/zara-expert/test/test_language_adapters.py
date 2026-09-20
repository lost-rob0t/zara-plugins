import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost
from zara_expert.language_adapters import (
    NIM_EXPERT,
    PROLOG_EXPERT,
    PYTHON_EXPERT,
    LanguageExpertAdapter,
    language_expert_schemas,
    profile_for_language,
)


class FakeBackend:
    def __init__(self):
        self.calls = []
        self.responses = {}

    def run(self, request):
        self.calls.append(dict(request))
        return self.responses.get(
            (request["namespace"], request["operation"]),
            {"ok": True, "results": ["ok"], "trace": []},
        )


class LanguageExpertAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.backend = FakeBackend()
        self.host = ExpertHost(
            self.backend,
            state_root=Path(self.temporary.name),
            query_timeout_seconds=1.0,
            max_results=16,
        )

    def tearDown(self):
        self.temporary.cleanup()

    def _adapter(self, profile=PROLOG_EXPERT):
        adapter = LanguageExpertAdapter(
            self.host,
            profile,
            source_reference=f"source:dotfiles.{profile.language}-expert",
            manifest_digest="sha256:" + "a" * 64,
            registry_generation=7,
            runtime_generation=11,
        )
        adapter.register([])
        return adapter

    def test_profiles_are_closed_and_match_language_family(self):
        self.assertIs(profile_for_language("prolog"), PROLOG_EXPERT)
        self.assertIs(profile_for_language("python"), PYTHON_EXPERT)
        self.assertIs(profile_for_language("nim"), NIM_EXPERT)
        with self.assertRaises(ExpertError):
            profile_for_language("rust")

        self.assertTrue(PROLOG_EXPERT.applies_to_path("src/rules.pl"))
        self.assertTrue(PYTHON_EXPERT.applies_to_path("src/app.py"))
        self.assertTrue(NIM_EXPERT.applies_to_path("src/app.nim"))
        self.assertFalse(PYTHON_EXPERT.applies_to_path("src/app.nim"))

    def test_descriptor_matches_zara_expert_1_symbolic_contract(self):
        descriptor = self._adapter().descriptor(
            node_id="desktop-node",
            runtime_id="zara-expert",
            available=True,
        )
        self.assertEqual(descriptor["protocol"], "ZARA-EXPERT/1")
        self.assertEqual(descriptor["expert_id"], "language:prolog")
        self.assertEqual(descriptor["reasoning_kind"], "symbolic")
        self.assertEqual(descriptor["fallback_policy"], "none")
        self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0)
        self.assertEqual(descriptor["manifest_digest"], "sha256:" + "a" * 64)
        self.assertEqual(descriptor["source_reference"], "source:dotfiles.prolog-expert")
        self.assertEqual(descriptor["registry_generation"], 7)
        self.assertIsNone(descriptor["unavailable_reason"])
        self.assertEqual(
            [operation["id"] for operation in descriptor["operations"]],
            ["applicable", "inspect", "diagnose", "style", "explain"],
        )

    def test_invoke_uses_existing_host_with_shared_budgets(self):
        adapter = self._adapter(PYTHON_EXPERT)
        result = adapter.invoke(
            "diagnose",
            "module_1",
            limits={
                "timeout_ms": 250,
                "max_results": 3,
                "max_output_bytes": 4096,
                "max_model_calls": 0,
            },
        )
        request = self.backend.calls[-1]
        self.assertEqual(request["namespace"], "python-expert")
        self.assertEqual(request["goal"], "expert_diagnostic(module_1, Result)")
        self.assertEqual(request["timeout_seconds"], 0.25)
        self.assertEqual(request["max_results"], 3)
        self.assertEqual(request["max_output_bytes"], 4096)
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["evidence"], ["ok"])

    def test_style_and_explain_use_fixed_predicates_and_preserve_evidence(self):
        adapter = self._adapter(NIM_EXPERT)
        self.backend.responses[("nim-expert", "query")] = {
            "ok": True,
            "results": ["indent(two_spaces)"],
            "trace": [],
        }
        style = adapter.invoke("style", "module_1")
        self.assertEqual(self.backend.calls[-1]["goal"], "expert_style_rule(module_1, Result)")
        self.assertEqual(style["evidence"], ["indent(two_spaces)"])

        self.backend.responses[("nim-expert", "explain")] = {
            "ok": True,
            "results": ["macro(expand_safe)"],
            "trace": ["rule:nim_macro/2", "compiler:nim-check"],
        }
        explained = adapter.invoke("explain", "module_1")
        self.assertEqual(self.backend.calls[-1]["goal"], "expert_explanation(module_1, Result)")
        self.assertEqual(explained["evidence"], ["macro(expand_safe)"])
        self.assertEqual(
            explained["explanation"],
            ["rule:nim_macro/2", "compiler:nim-check"],
        )

    def test_model_budget_and_subject_injection_fail_before_backend(self):
        adapter = self._adapter()
        before = len(self.backend.calls)
        with self.assertRaisesRegex(ExpertError, "max_model_calls"):
            adapter.invoke(
                "inspect",
                "module_1",
                limits={
                    "timeout_ms": 1000,
                    "max_results": 16,
                    "max_output_bytes": 65536,
                    "max_model_calls": 1,
                },
            )
        with self.assertRaisesRegex(ExpertError, "subject_id"):
            adapter.invoke("inspect", "x);shell(rm)")
        with self.assertRaisesRegex(ExpertError, "unsupported language expert operation"):
            adapter.invoke("rewrite", "module_1")
        self.assertEqual(len(self.backend.calls), before)

    def test_unavailable_descriptor_is_typed(self):
        descriptor = self._adapter().descriptor(
            node_id="desktop-node",
            runtime_id="zara-expert",
            available=False,
            unavailable_reason="canonical-source-not-installed",
        )
        self.assertEqual(descriptor["availability"], "unavailable")
        self.assertEqual(descriptor["unavailable_reason"], "canonical-source-not-installed")

    def test_schema_refs_are_exposed_without_a_second_registry(self):
        schemas = language_expert_schemas()
        self.assertEqual(
            set(schemas),
            {
                "schema:zara.language-expert.subject.v1",
                "schema:zara.language-expert.result.v1",
            },
        )
        self.assertFalse(schemas["schema:zara.language-expert.subject.v1"]["additionalProperties"])
        self.assertFalse(schemas["schema:zara.language-expert.result.v1"]["additionalProperties"])


if __name__ == "__main__":
    unittest.main()
