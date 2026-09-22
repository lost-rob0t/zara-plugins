from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]

CASES = {
    "prolog": ("zara-prolog-expert", "zara_prolog_expert", "Prolog"),
    "python": ("zara-python-expert", "zara_python_expert", "Python"),
    "nim": ("zara-nim-expert", "zara_nim_expert", "Nim"),
}

CANONICAL_DESCRIPTOR_FIELDS = {
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
    "unavailable_reason",
}


def _install_stubs() -> None:
    plugins = types.ModuleType("zara.plugins")

    class PluginMetadata:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class ServicePlugin:
        pass

    plugins.PluginMetadata = PluginMetadata
    plugins.ServicePlugin = ServicePlugin
    zara = types.ModuleType("zara")
    zara.plugins = plugins
    sys.modules["zara"] = zara
    sys.modules["zara.plugins"] = plugins


def _load(package: str, module_name: str):
    _install_stubs()
    path = ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(f"test_canonical_{module_name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrologPythonNimCanonicalDescriptorTests(unittest.TestCase):
    def test_descriptor_matches_zara_expert_v1_applicability_shape(self):
        """Zara #1233 accepts applicability keywords only; language extensions stay adapter-local."""
        for language, (package, module_name, class_name) in CASES.items():
            module = _load(package, module_name)
            plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
            descriptor = json.loads(plugin.descriptor())

            self.assertTrue(set(descriptor) <= CANONICAL_DESCRIPTOR_FIELDS, language)
            self.assertEqual(
                descriptor["applicability"],
                {"keywords": list(module.LANGUAGE_BOUNDARIES["applicability_keywords"])},
                language,
            )
            self.assertTrue(module.LANGUAGE_BOUNDARIES["extensions"], language)
            self.assertNotIn("extensions", descriptor["applicability"], language)

    def test_explanation_style_and_evidence_remain_exposed_through_canonical_operations(self):
        for language, (package, module_name, class_name) in CASES.items():
            module = _load(package, module_name)
            plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
            descriptor = json.loads(plugin.descriptor())
            operations = {item["operation_id"]: item for item in descriptor["operations"]}

            self.assertEqual(
                {field["name"] for field in operations["style.rules"]["output_schema"]["fields"]},
                {"style_rules", "style_provenance"},
                language,
            )
            self.assertEqual(
                {field["name"] for field in operations["explain"]["output_schema"]["fields"]},
                {"explanation"},
                language,
            )
            self.assertIn("evidence_topics", module.LANGUAGE_BOUNDARIES, language)
            self.assertTrue(module.LANGUAGE_BOUNDARIES["evidence_topics"], language)
            self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0, language)
            self.assertEqual(descriptor["required_capabilities"], ["expert.invoke"], language)


if __name__ == "__main__":
    unittest.main()
