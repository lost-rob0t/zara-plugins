import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost
from zara_expert.language_family import (
    MAX_MODEL_CALLS,
    PROTOCOL,
    descriptors,
    invoke_language_operation,
    language_expert_schemas,
    language_family_specs,
    matching_experts,
    register_descriptor_symbols,
    register_language_family,
    registered_predicates,
)
from zara_expert.plugin import ZaraExpertPlugin


class RecordingBackend:
    def __init__(self):
        self.calls = []

    def run(self, request):
        self.calls.append(dict(request))
        return {
            "ok": True,
            "results": ["evidence:compiler"],
            "trace": ["rule:style", "source:canonical"],
        }


class RecordingRuntime:
    def __init__(self, configuration=None):
        self.configuration = configuration or {}
        self.registrations = []

    def register_symbol(self, symbol, kind, value, **metadata):
        self.registrations.append((symbol, kind, value, metadata))
        return len(self.registrations)


class LanguageFamilyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = RecordingBackend()
        self.host = ExpertHost(self.backend, state_root=self.root / "state")

    def tearDown(self):
        self.temporary.cleanup()

    def _brain(self, name):
        path = self.root / f"{name}.pl"
        path.write_text("% canonical-language-brain-fixture\n", encoding="utf-8")
        return path

    def test_descriptors_are_symbolic_provider_free_zero_model_and_typed(self):
        items = descriptors()
        self.assertEqual(
            [item["expert_id"] for item in items],
            ["prolog", "python", "nim"],
        )
        for item in items:
            with self.subTest(expert=item["expert_id"]):
                self.assertEqual(item["protocol"], PROTOCOL)
                self.assertEqual(item["reasoning_kind"], "symbolic")
                self.assertEqual(item["resource_limits"]["max_model_calls"], 0)
                self.assertEqual(
                    item["fallback"],
                    {"provider": False, "model": False, "remote": False},
                )
                self.assertEqual(item["availability"], "source-unavailable")
                self.assertTrue(item["source_reference"].startswith("dotfiles:.zara/experts/"))
                self.assertEqual(
                    item["applicability_schema"],
                    "schema:zara.language-expert.applicability.v1",
                )
        self.assertEqual(MAX_MODEL_CALLS, 0)

    def test_language_applicability_is_deterministic(self):
        self.assertEqual(matching_experts("rules/foo.pl"), ("prolog",))
        self.assertEqual(matching_experts("src/main.py"), ("python",))
        self.assertEqual(matching_experts("src/main.nim"), ("nim",))
        self.assertEqual(matching_experts("README.md"), ())

        specs = {spec.expert_id: spec for spec in language_family_specs()}
        self.assertIn(".pyi", specs["python"].extensions)
        self.assertIn(".nimble", specs["nim"].extensions)

    def test_operation_bindings_are_registered_predicates_not_raw_goals(self):
        for item in descriptors():
            for operation in item["operations"]:
                if operation["name"] == "repair.apply":
                    self.assertIsNone(operation["binding"])
                    continue
                binding = operation["binding"]
                self.assertEqual(binding["authority"], "registered-predicate")
                self.assertIn(binding["predicate"], registered_predicates())
                self.assertNotIn("goal", binding)
                self.assertNotIn("shell", binding)

    def test_registered_language_invocation_preserves_evidence_and_explanation(self):
        source = self._brain("python")
        registered = register_language_family(self.host, {"python": [source]})
        self.assertEqual(registered, frozenset({"python"}))

        result = invoke_language_operation(
            self.host,
            "python",
            "style.rules",
            ["src/main.py", "project-style", {"var": "Result"}],
        )
        self.assertEqual(result["protocol"], PROTOCOL)
        self.assertEqual(result["expert_id"], "python")
        self.assertEqual(result["evidence"], ["evidence:compiler"])
        self.assertEqual(result["explanation"], ["rule:style", "source:canonical"])
        self.assertEqual(result["model_calls"], 0)
        call = self.backend.calls[-1]
        self.assertEqual(call["capability"].predicate, "language_style_rules")
        self.assertNotIn("goal", call)
        self.assertNotIn("predicate", call)

    def test_source_like_inert_argument_never_becomes_executable_goal(self):
        source = self._brain("prolog")
        register_language_family(self.host, {"prolog": [source]})
        payload = "x'); shell('touch /tmp/pwned') %"
        invoke_language_operation(
            self.host,
            "prolog",
            "inspect",
            [payload, "generation-1", {"var": "Evidence"}],
        )
        call = self.backend.calls[-1]
        self.assertEqual(call["arguments"][0], payload)
        self.assertNotIn("goal", call)

    def test_apply_never_bypasses_canonical_edit_effect_boundary(self):
        source = self._brain("nim")
        register_language_family(self.host, {"nim": [source]})
        with self.assertRaisesRegex(ExpertError, "canonical typed edit/effect path"):
            invoke_language_operation(
                self.host,
                "nim",
                "repair.apply",
                ["candidate", "expected-preimage"],
            )
        self.assertEqual(self.backend.calls, [])

    def test_unknown_sources_and_operations_fail_closed(self):
        with self.assertRaisesRegex(ExpertError, "regular file"):
            register_language_family(self.host, {"python": [self.root / "missing.pl"]})
        with self.assertRaisesRegex(ExpertError, "unknown language expert source keys"):
            register_language_family(self.host, {"rust": [self._brain("rust")]})
        source = self._brain("python-ok")
        register_language_family(self.host, {"python": [source]})
        with self.assertRaisesRegex(ExpertError, "unsupported language expert operation"):
            invoke_language_operation(self.host, "python", "execute.shell", [])

    def test_schema_surface_is_closed_and_zero_model(self):
        schemas = language_expert_schemas()
        applicability = schemas["schema:zara.language-expert.applicability.v1"]
        result = schemas["schema:zara.language-expert.result.v1"]
        self.assertFalse(applicability["additionalProperties"])
        self.assertFalse(result["additionalProperties"])
        self.assertEqual(result["properties"]["model_calls"], {"const": 0})

    def test_descriptor_symbols_use_canonical_runtime_registry(self):
        runtime = RecordingRuntime()
        ids = register_descriptor_symbols(runtime, {"prolog", "nim"})
        self.assertEqual(ids, (1, 2, 3))
        self.assertEqual(
            [item[0] for item in runtime.registrations],
            ["zara:expert/prolog", "zara:expert/python", "zara:expert/nim"],
        )
        for _, kind, value, metadata in runtime.registrations:
            self.assertEqual(kind, "expert")
            self.assertEqual(value["resource_limits"]["max_model_calls"], 0)
            self.assertEqual(metadata["capabilities"], ())

    def test_plugin_start_exposes_configured_language_brain_without_credentials(self):
        source = self._brain("python-plugin")
        runtime = RecordingRuntime(
            {
                "language_expert_sources": {
                    "python": [str(source)],
                }
            }
        )
        plugin = ZaraExpertPlugin(backend=self.backend, state_root=self.root / "plugin-state")
        plugin.start(runtime)

        rendered = json.loads(plugin.language_family_descriptors())
        availability = {item["expert_id"]: item["availability"] for item in rendered}
        self.assertEqual(availability["python"], "available")
        self.assertEqual(availability["prolog"], "source-unavailable")
        status = json.loads(plugin.status())
        self.assertEqual(status["model_calls"], 0)
        self.assertEqual(status["language_family"], ["python"])
        self.assertEqual(len(runtime.registrations), 6)


if __name__ == "__main__":
    unittest.main()
