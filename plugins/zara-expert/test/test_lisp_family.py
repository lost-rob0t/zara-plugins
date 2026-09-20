import inspect
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_expert.domain import ExpertError, ExpertHost
from zara_expert.lisp_family import (
    MAX_MODEL_CALLS,
    PROTOCOL,
    RESERVED_HOST_INPUT_FIELDS,
    descriptors,
    invoke_lisp_operation,
    make_lisp_expert_handler,
    register_descriptor_symbols,
    register_lisp_family,
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
            "results": ["symbolic-result"],
            "trace": ["registered-predicate"],
        }


class RecordingRuntime:
    def __init__(self, configuration=None):
        self.configuration = configuration or {}
        self.registrations = []

    def register_symbol(self, symbol, kind, value, **metadata):
        self.registrations.append((symbol, kind, value, metadata))
        return len(self.registrations)


class LispFamilyAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.backend = RecordingBackend()
        self.host = ExpertHost(self.backend, state_root=self.root / "state")

    def tearDown(self):
        self.temporary.cleanup()

    def _brain(self, name):
        path = self.root / f"{name}.pl"
        path.write_text("% canonical-brain-fixture\n", encoding="utf-8")
        return path

    def test_descriptors_are_canonical_symbolic_provider_free_and_zero_model(self):
        items = descriptors()
        self.assertEqual(
            [item["expert_id"] for item in items],
            [
                "zara:expert/lisp",
                "zara:expert/common-lisp",
                "zara:expert/emacs-lisp",
            ],
        )
        for item in items:
            with self.subTest(expert=item["expert_id"]):
                self.assertEqual(item["protocol"], PROTOCOL)
                self.assertEqual(item["reasoning_kind"], "symbolic")
                self.assertEqual(item["resource_limits"]["max_model_calls"], 0)
                self.assertEqual(item["fallback_policy"], "fail_closed")
                self.assertNotIn("model_inference", item["possible_effects"])
                self.assertEqual(item["availability"], "absent")
                self.assertEqual(item["unavailable_reason"], "source-unavailable")
                self.assertTrue(item["source_reference"].startswith("dotfiles:.zara/experts/"))
                self.assertTrue(item["manifest_digest"].startswith("sha256:"))
                self.assertEqual(len(item["manifest_digest"].split(":", 1)[1]), 64)
        self.assertEqual(MAX_MODEL_CALLS, 0)

    def test_public_descriptor_does_not_leak_private_predicate_authority(self):
        private_predicates = set(registered_predicates())
        self.assertTrue(private_predicates)
        for item in descriptors():
            keys = set(item)
            self.assertEqual(keys - {"unavailable_reason"}, _CANONICAL_DESCRIPTOR_KEYS)
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

    def test_descriptor_inputs_never_claim_core_owned_host_metadata(self):
        self.assertEqual(RESERVED_HOST_INPUT_FIELDS, frozenset({"expert_operation"}))
        for item in descriptors():
            for operation in item["operations"]:
                names = {field["name"] for field in operation["input_schema"]["fields"]}
                self.assertTrue(names.isdisjoint(RESERVED_HOST_INPUT_FIELDS))

    def test_dialect_specializations_declare_canonical_child_delegation(self):
        items = {item["expert_id"]: item for item in descriptors()}
        self.assertEqual(items["zara:expert/lisp"]["delegation_policy"], "never")
        self.assertEqual(items["zara:expert/common-lisp"]["delegation_policy"], "children")
        self.assertEqual(items["zara:expert/emacs-lisp"]["delegation_policy"], "children")

    def test_structural_apply_never_bypasses_canonical_effect_boundary(self):
        source = self._brain("lisp")
        registered = register_lisp_family(self.host, {"lisp": [source]})
        self.assertEqual(registered, frozenset({"lisp"}))
        with self.assertRaisesRegex(ExpertError, "canonical typed edit/effect path"):
            invoke_lisp_operation(
                self.host,
                "lisp",
                "repair.apply",
                ["candidate", "expected-preimage"],
            )
        self.assertEqual(self.backend.calls, [])

    def test_core_handler_uses_host_owned_operation_and_exact_zero_model_ledger(self):
        source = self._brain("lisp")
        register_lisp_family(self.host, {"lisp": [source]})
        handler = make_lisp_expert_handler(self.host, "zara:expert/lisp")

        signature = inspect.signature(handler)
        operation_parameter = signature.parameters["expert_operation"]
        self.assertEqual(operation_parameter.kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(operation_parameter.default, inspect.Parameter.empty)

        outcome = handler(
            expert_operation="structural.check",
            arguments=["(list)", {"var": "Evidence"}],
        )

        self.assertEqual(outcome["verdict"], "succeeded")
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])
        self.assertEqual(outcome["data"]["result"]["results"], ["symbolic-result"])
        self.assertEqual(self.backend.calls[-1]["capability"].predicate, "structural_check")

    def test_core_handler_blocks_repair_apply_before_backend_effects(self):
        handler = make_lisp_expert_handler(self.host, "zara:expert/lisp")

        outcome = handler(
            expert_operation="repair.apply",
            repair={"kind": "insert", "text": ")"},
            expected_preimage="sha256:fixture",
            source_generation="buffer:7",
        )

        self.assertEqual(outcome["verdict"], "blocked")
        self.assertEqual(outcome["usage"], {"model_calls": 0})
        self.assertEqual(outcome["effect_receipts"], [])
        self.assertEqual(outcome["data"]["reason"], "canonical-typed-edit-required")
        self.assertEqual(self.backend.calls, [])

    def test_base_preview_and_dialect_verify_use_registered_predicate_capabilities(self):
        lisp_source = self._brain("lisp")
        common_source = self._brain("common-lisp")
        register_lisp_family(
            self.host,
            {"lisp": [lisp_source], "common-lisp": [common_source]},
        )

        preview = invoke_lisp_operation(
            self.host,
            "lisp",
            "repair.preview",
            ["(defun x ()", "missing-close", {"var": "Repair"}],
        )
        verify = invoke_lisp_operation(
            self.host,
            "zara:expert/common-lisp",
            "repair.verify",
            ["(defun x ()", "(defun x ())", {"var": "Evidence"}],
        )

        self.assertEqual(preview["results"], ["symbolic-result"])
        self.assertEqual(verify["results"], ["symbolic-result"])
        self.assertEqual(
            [call["capability"].predicate for call in self.backend.calls],
            ["preview_repair", "verify_repair"],
        )
        self.assertNotIn("goal", self.backend.calls[0])
        self.assertNotIn("predicate", self.backend.calls[0])

    def test_dialect_preview_fails_closed_until_canonical_shared_budget_delegation(self):
        common_source = self._brain("common-lisp")
        register_lisp_family(self.host, {"common-lisp": [common_source]})

        with self.assertRaisesRegex(
            ExpertError,
            "canonical ZARA-EXPERT/1 delegation to zara:expert/lisp",
        ):
            invoke_lisp_operation(
                self.host,
                "common-lisp",
                "repair.preview",
                ["(defun x ()", "missing-close", {"var": "Repair"}],
            )
        self.assertEqual(self.backend.calls, [])

    def test_configured_sources_are_files_and_unknown_adapters_fail_closed(self):
        with self.assertRaisesRegex(ExpertError, "regular file"):
            register_lisp_family(self.host, {"lisp": [self.root / "missing.pl"]})
        with self.assertRaisesRegex(ExpertError, "unknown Lisp expert source keys"):
            register_lisp_family(self.host, {"scheme": [self._brain("scheme")]})
        self.assertEqual(self.backend.calls, [])

    def test_source_preflight_is_atomic_before_namespace_registration(self):
        lisp_source = self._brain("lisp")
        missing_common = self.root / "missing-common-lisp.pl"

        with self.assertRaisesRegex(ExpertError, "regular file"):
            register_lisp_family(
                self.host,
                {
                    "lisp": [lisp_source],
                    "common-lisp": [missing_common],
                },
            )

        with self.assertRaisesRegex(ExpertError, "namespace 'lisp' is not registered"):
            invoke_lisp_operation(
                self.host,
                "lisp",
                "structural.check",
                ["(list)", {"var": "Evidence"}],
            )
        self.assertEqual(self.backend.calls, [])

    def test_authority_preflight_is_atomic_before_family_registration(self):
        original_common = self._brain("common-original")
        replacement_common = self._brain("common-replacement")
        lisp_source = self._brain("lisp")
        self.host.register(
            "common-lisp",
            [original_common],
            predicates=registered_predicates(),
        )

        with self.assertRaisesRegex(ExpertError, "different authority"):
            register_lisp_family(
                self.host,
                {
                    "lisp": [lisp_source],
                    "common-lisp": [replacement_common],
                },
            )

        with self.assertRaisesRegex(ExpertError, "namespace 'lisp' is not registered"):
            invoke_lisp_operation(
                self.host,
                "lisp",
                "structural.check",
                ["(list)", {"var": "Evidence"}],
            )
        self.host.query("common-lisp", "structural_check", ["(list)", {"var": "Evidence"}])
        self.assertEqual(self.backend.calls[-1]["knowledge_bases"], (str(original_common.resolve()),))

    def test_descriptor_symbols_use_canonical_runtime_registry(self):
        runtime = RecordingRuntime()
        ids = register_descriptor_symbols(runtime, {"lisp", "emacs-lisp"})
        self.assertEqual(ids, (1, 2, 3))
        self.assertEqual(
            [item[0] for item in runtime.registrations],
            ["zara:expert/lisp", "zara:expert/common-lisp", "zara:expert/emacs-lisp"],
        )
        for _, kind, value, metadata in runtime.registrations:
            self.assertEqual(kind, "expert")
            self.assertEqual(value["protocol"], PROTOCOL)
            self.assertEqual(value["resource_limits"]["max_model_calls"], 0)
            self.assertEqual(metadata["capabilities"], ())

    def test_plugin_start_registers_configured_brain_without_provider_credentials(self):
        source = self._brain("emacs-lisp")
        runtime = RecordingRuntime(
            {
                "lisp_family_sources": {
                    "emacs-lisp": [str(source)],
                }
            }
        )
        plugin = ZaraExpertPlugin(backend=self.backend, state_root=self.root / "plugin-state")
        plugin.start(runtime)

        rendered = json.loads(plugin.lisp_family_descriptors())
        availability = {item["expert_id"]: item["availability"] for item in rendered}
        self.assertEqual(availability["zara:expert/emacs-lisp"], "available")
        self.assertEqual(availability["zara:expert/lisp"], "absent")
        self.assertEqual(json.loads(plugin.status())["model_calls"], 0)
        expected_lisp_symbols = [
            "zara:expert/lisp",
            "zara:expert/common-lisp",
            "zara:expert/emacs-lisp",
        ]
        registered_symbols = [item[0] for item in runtime.registrations]
        self.assertEqual(
            [symbol for symbol in registered_symbols if symbol in expected_lisp_symbols],
            expected_lisp_symbols,
        )
        self.assertEqual(len(registered_symbols), len(set(registered_symbols)))

        handler = plugin.lisp_expert_handler("zara:expert/emacs-lisp")
        self.assertIn("expert_operation", inspect.signature(handler).parameters)

    def test_lisp_family_does_not_export_parallel_invocation_or_descriptor_tools(self):
        plugin = ZaraExpertPlugin(backend=self.backend, state_root=self.root / "plugin-state")
        names = {tool.name for tool in plugin.tools()}
        self.assertNotIn("expert.lisp_invoke", names)
        self.assertNotIn("expert.lisp_descriptors", names)
        self.assertIn("expert.query", names)
        self.assertIn("expert.explain", names)


if __name__ == "__main__":
    unittest.main()
