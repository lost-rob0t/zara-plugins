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


_CANONICAL_DESCRIPTOR_KEYS = {
    "protocol",
    "expert_id",
    "expert_version",
    "package_namespace",
    "manifest_digest",
    "name",
    "description",
    "source_reference",
    "reasoning_kind",
    "operations",
    "applicability",
    "required_capabilities",
    "possible_effects",
    "supported_engines",
    "supported_platforms",
    "fallback_policy",
    "delegation_policy",
    "resource_limits",
    "registry_generation",
    "availability",
}


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

    def test_descriptors_match_canonical_zara_expert_shape(self):
        items = descriptors()
        self.assertEqual(
            [item["expert_id"] for item in items],
            ["zara:expert/prolog", "zara:expert/python", "zara:expert/nim"],
        )
        private_predicates = set(registered_predicates())
        self.assertTrue(private_predicates)

        for item in items:
            with self.subTest(expert=item["expert_id"]):
                self.assertEqual(item["protocol"], PROTOCOL)
                self.assertEqual(item["reasoning_kind"], "symbolic")
                self.assertEqual(item["resource_limits"]["max_model_calls"], 0)
                self.assertEqual(item["fallback_policy"], "fail_closed")
                self.assertNotIn("model_inference", item["possible_effects"])
                self.assertEqual(item["availability"], "absent")
                self.assertEqual(item["unavailable_reason"], "source-unavailable")
                self.assertTrue(item["manifest_digest"].startswith("sha256:"))
                self.assertEqual(len(item["manifest_digest"].split(":", 1)[1]), 64)
                self.assertEqual(
                    set(item) - {"unavailable_reason"},
                    _CANONICAL_DESCRIPTOR_KEYS,
                )
                rendered = json.dumps(item, sort_keys=True)
                for predicate in private_predicates:
                    self.assertNotIn(predicate, rendered)
                for operation in item["operations"]:
                    self.assertEqual(
                        set(operation),
                        {"operation_id", "input_schema", "output_schema"},
                    )
                    self.assertEqual(set(operation["input_schema"]), {"fields"})
                    self.assertEqual(set(operation["output_schema"]), {"fields"})
        self.assertEqual(MAX_MODEL_CALLS, 0)

    def test_language_applicability_is_deterministic_and_canonical(self):
        self.assertEqual(
            matching_experts("rules/foo.pl"),
            ("zara:expert/prolog",),
        )
        self.assertEqual(
            matching_experts("src/main.py"),
            ("zara:expert/python",),
        )
        self.assertEqual(
            matching_experts("src/main.nim"),
            ("zara:expert/nim",),
        )
        self.assertEqual(matching_experts("README.md"), ())

        specs = {spec.key: spec for spec in language_family_specs()}
        self.assertIn(".pyi", specs["python"].extensions)
        self.assertIn(".nimble", specs["nim"].extensions)
        self.assertIn("dcg", specs["prolog"].applicability_keywords)

    def test_registered_predicate_authority_is_private_to_host(self):
        source = self._brain("python")
        registered = register_language_family(self.host, {"python": [source]})
        self.assertEqual(registered, frozenset({"python"}))

        result = invoke_language_operation(
            self.host,
            "zara:expert/python",
            "style.rules",
            ["src/main.py", "project-style", {"var": "Result"}],
        )
        self.assertEqual(result["protocol"], PROTOCOL)
        self.assertEqual(result["expert_id"], "zara:expert/python")
        self.assertEqual(result["evidence"], ["evidence:compiler"])
        self.assertEqual(
            result["explanation"],
            ["rule:style", "source:canonical"],
        )
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["effect_receipts"], [])

        call = self.backend.calls[-1]
        self.assertEqual(call["capability"].predicate, "language_style_rules")
        self.assertNotIn("goal", call)
        self.assertNotIn("predicate", call)

    def test_source_like_argument_remains_inert_data(self):
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

    def test_apply_never_bypasses_canonical_effect_boundary(self):
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
            register_language_family(
                self.host,
                {"python": [self.root / "missing.pl"]},
            )
        with self.assertRaisesRegex(ExpertError, "unknown language expert source keys"):
            register_language_family(
                self.host,
                {"rust": [self._brain("rust")]},
            )
        source = self._brain("python-ok")
        register_language_family(self.host, {"python": [source]})
        with self.assertRaisesRegex(
            ExpertError,
            "unsupported language expert operation",
        ):
            invoke_language_operation(self.host, "python", "execute.shell", [])

    def test_source_preflight_is_atomic_before_namespace_registration(self):
        prolog_source = self._brain("prolog-atomic")
        missing_python = self.root / "missing-python.pl"

        with self.assertRaisesRegex(ExpertError, "regular file"):
            register_language_family(
                self.host,
                {
                    "prolog": [prolog_source],
                    "python": [missing_python],
                },
            )

        with self.assertRaisesRegex(ExpertError, "namespace 'prolog-expert' is not registered"):
            invoke_language_operation(
                self.host,
                "prolog",
                "inspect",
                ["fact(a).", "generation-1", {"var": "Evidence"}],
            )
        self.assertEqual(self.backend.calls, [])

    def test_operation_schemas_expose_evidence_explanation_and_style_provenance(self):
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
        style_fields = {
            field["name"]
            for field in schemas["style.rules"]["output_schema"]["fields"]
        }
        self.assertEqual(
            style_fields,
            {
                "style_rules",
                "style_provenance",
                "evidence_refs",
                "explanation_refs",
            },
        )
        verify_fields = {
            field["name"]
            for field in schemas["repair.verify"]["output_schema"]["fields"]
        }
        self.assertIn("postcondition_evidence", verify_fields)

    def test_descriptor_symbols_use_canonical_runtime_registry(self):
        runtime = RecordingRuntime()
        ids = register_descriptor_symbols(runtime, {"prolog", "nim"})
        self.assertEqual(ids, (1, 2, 3))
        self.assertEqual(
            [item[0] for item in runtime.registrations],
            [
                "zara:expert/prolog",
                "zara:expert/python",
                "zara:expert/nim",
            ],
        )
        availability = {
            value["expert_id"]: value["availability"]
            for _, _, value, _ in runtime.registrations
        }
        self.assertEqual(availability["zara:expert/prolog"], "available")
        self.assertEqual(availability["zara:expert/python"], "absent")
        self.assertEqual(availability["zara:expert/nim"], "available")
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
        plugin = ZaraExpertPlugin(
            backend=self.backend,
            state_root=self.root / "plugin-state",
        )
        plugin.start(runtime)

        rendered = json.loads(plugin.language_family_descriptors())
        availability = {
            item["expert_id"]: item["availability"]
            for item in rendered
        }
        self.assertEqual(availability["zara:expert/python"], "available")
        self.assertEqual(availability["zara:expert/prolog"], "absent")
        status = json.loads(plugin.status())
        self.assertEqual(status["model_calls"], 0)
        self.assertEqual(status["language_family"], ["python"])
        self.assertEqual(len(runtime.registrations), 6)

    def test_language_family_exports_no_parallel_descriptor_or_invoke_tools(self):
        plugin = ZaraExpertPlugin(
            backend=self.backend,
            state_root=self.root / "plugin-state",
        )
        names = {tool.name for tool in plugin.tools()}
        self.assertNotIn("expert.language_invoke", names)
        self.assertNotIn("expert.language_descriptors", names)
        self.assertNotIn("expert.language_schemas", names)
        self.assertNotIn("expert.lisp_invoke", names)
        self.assertNotIn("expert.lisp_descriptors", names)
        self.assertIn("expert.query", names)
        self.assertIn("expert.explain", names)


if __name__ == "__main__":
    unittest.main()