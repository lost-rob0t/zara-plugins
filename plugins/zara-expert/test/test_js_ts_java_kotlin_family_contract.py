import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertHost
from zara_expert.language_family import (
    descriptors,
    invoke_language_operation,
    language_family_specs,
    matching_experts,
    register_language_family,
    registered_predicates,
)


EXPECTED = {
    "javascript": {
        "expert_id": "zara:expert/javascript",
        "namespace": "javascript-expert",
        "extensions": (".js", ".jsx", ".mjs", ".cjs"),
        "source_reference": "dotfiles:.zara/experts/javascript",
        "upstream_issue": "lost-rob0t/prolog-rlm#500",
    },
    "typescript": {
        "expert_id": "zara:expert/typescript",
        "namespace": "typescript-expert",
        "extensions": (".ts", ".tsx", ".mts", ".cts"),
        "source_reference": "dotfiles:.zara/experts/typescript",
        "upstream_issue": "lost-rob0t/prolog-rlm#500",
    },
    "java": {
        "expert_id": "zara:expert/java",
        "namespace": "java-expert",
        "extensions": (".java",),
        "source_reference": "dotfiles:.zara/experts/java",
        "upstream_issue": "lost-rob0t/prolog-rlm#501",
    },
    "kotlin": {
        "expert_id": "zara:expert/kotlin",
        "namespace": "kotlin-expert",
        "extensions": (".kt", ".kts"),
        "source_reference": "dotfiles:.zara/experts/kotlin",
        "upstream_issue": "lost-rob0t/prolog-rlm#501",
    },
}


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return {
            "ok": True,
            "results": ["evidence:canonical-brain"],
            "trace": ["source:dotfiles"],
        }


class JavaScriptTypeScriptJavaKotlinHostContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = RecordingBackend()
        self.host = ExpertHost(self.backend, state_root=self.root / "state")

    def tearDown(self):
        self.temporary.cleanup()

    def _brain(self, name):
        path = self.root / f"{name}.pl"
        exports = [
            *(f"{predicate}/{arity}" for predicate, arity in registered_predicates().items()),
            "provider_policy/1",
            "max_model_calls/1",
            "model_calls/1",
        ]
        path.write_text(
            f":- module({name.replace('-', '_')}, [{', '.join(exports)}]).\n"
            "provider_policy(disabled).\n"
            "max_model_calls(0).\n"
            "model_calls(0).\n",
            encoding="utf-8",
        )
        return path

    def test_family_exposes_four_distinct_canonical_experts(self):
        specs = {spec.key: spec for spec in language_family_specs()}

        for key, expected in EXPECTED.items():
            with self.subTest(expert=key):
                self.assertIn(key, specs)
                spec = specs[key]
                self.assertEqual(spec.expert_id, expected["expert_id"])
                self.assertEqual(spec.namespace, expected["namespace"])
                self.assertEqual(spec.extensions, expected["extensions"])
                self.assertEqual(spec.source_reference, expected["source_reference"])
                self.assertEqual(spec.upstream_issue, expected["upstream_issue"])

    def test_extension_routing_never_collapses_sibling_languages(self):
        self.assertEqual(matching_experts("src/app.js"), ("zara:expert/javascript",))
        self.assertEqual(matching_experts("src/app.jsx"), ("zara:expert/javascript",))
        self.assertEqual(matching_experts("src/app.ts"), ("zara:expert/typescript",))
        self.assertEqual(matching_experts("src/app.tsx"), ("zara:expert/typescript",))
        self.assertEqual(matching_experts("src/Main.java"), ("zara:expert/java",))
        self.assertEqual(matching_experts("src/Main.kt"), ("zara:expert/kotlin",))
        self.assertEqual(matching_experts("build.gradle.kts"), ("zara:expert/kotlin",))

    def test_descriptors_are_zero_model_and_provider_free(self):
        by_id = {item["expert_id"]: item for item in descriptors()}

        for expected in EXPECTED.values():
            expert_id = expected["expert_id"]
            with self.subTest(expert=expert_id):
                self.assertIn(expert_id, by_id)
                item = by_id[expert_id]
                self.assertEqual(item["reasoning_kind"], "symbolic")
                self.assertEqual(item["fallback_policy"], "fail_closed")
                self.assertEqual(item["resource_limits"]["max_model_calls"], 0)
                self.assertNotIn("model_inference", item["possible_effects"])

    def test_each_brain_registers_and_invokes_through_existing_host_authority(self):
        sources = {key: [self._brain(key)] for key in EXPECTED}
        registered = register_language_family(self.host, sources)
        self.assertEqual(registered, frozenset(EXPECTED))

        for key, expected in EXPECTED.items():
            with self.subTest(expert=key):
                result = invoke_language_operation(
                    self.host,
                    expected["expert_id"],
                    "inspect",
                    ["inert source observation", "generation-1", {"var": "Evidence"}],
                )
                self.assertEqual(result["expert_id"], expected["expert_id"])
                self.assertEqual(result["model_calls"], 0)
                self.assertEqual(result["effect_receipts"], [])

        self.assertEqual(len(self.backend.calls), len(EXPECTED))
        for call in self.backend.calls:
            self.assertNotIn("goal", call)
            self.assertNotIn("provider", call)
            self.assertNotIn("model", call)


if __name__ == "__main__":
    unittest.main()
