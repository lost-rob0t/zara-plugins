from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
import types
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOST_LIB = ROOT / "plugins" / "zara-expert" / "lib"
if str(HOST_LIB) not in sys.path:
    sys.path.insert(0, str(HOST_LIB))

from zara_expert.language_family import language_family_specs


CASES = {
    "prolog": ("zara-prolog-expert", "zara_prolog_expert", "Prolog"),
    "python": ("zara-python-expert", "zara_python_expert", "Python"),
    "nim": ("zara-nim-expert", "zara_nim_expert", "Nim"),
}
KEYWORD_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
MAX_KEYWORDS = 32


def _install_zara_stubs() -> None:
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


def _load_product(package: str, module_name: str, suffix: str):
    _install_zara_stubs()
    path = ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        f"test_canonical_provenance_{module_name}_{suffix}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrologPythonNimCanonicalProvenanceTests(unittest.TestCase):
    def test_product_descriptor_reuses_host_language_identity_and_source(self) -> None:
        """One expert identity must have one applicability/source contract."""
        host_specs = {spec.key: spec for spec in language_family_specs()}

        for language, (package, module_name, class_name) in CASES.items():
            with self.subTest(language=language):
                host = host_specs[language]
                module = _load_product(package, module_name, "first")
                plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
                descriptor_text = plugin.descriptor()
                descriptor = json.loads(descriptor_text)

                lock = json.loads(
                    (ROOT / "plugins" / package / "expert-source.lock.json").read_text(
                        encoding="utf-8"
                    )
                )
                locked_source = f"dotfiles:{lock['canonical_source']['path']}"
                locked_upstream = (
                    f"{lock['runtime_contract']['repository']}"
                    f"#{lock['runtime_contract']['issue']}"
                )

                self.assertEqual(host.source_reference, locked_source)
                self.assertEqual(module.SOURCE_REFERENCE, host.source_reference)
                self.assertEqual(descriptor["source_reference"], host.source_reference)
                self.assertEqual(module.EXPERT_ID, host.expert_id)
                self.assertEqual(descriptor["expert_id"], host.expert_id)
                self.assertEqual(module.UPSTREAM_CONTRACT, host.upstream_issue)
                self.assertEqual(module.UPSTREAM_CONTRACT, locked_upstream)
                self.assertEqual(
                    tuple(module.LANGUAGE_BOUNDARIES["extensions"]), host.extensions
                )
                self.assertEqual(
                    tuple(module.LANGUAGE_BOUNDARIES["applicability_keywords"]),
                    host.applicability_keywords,
                )

                keywords = descriptor["applicability"]["keywords"]
                self.assertEqual(tuple(keywords), host.applicability_keywords)
                self.assertLessEqual(len(keywords), MAX_KEYWORDS)
                self.assertEqual(len(keywords), len(set(keywords)))
                self.assertTrue(
                    all(
                        type(keyword) is str and KEYWORD_RE.fullmatch(keyword) is not None
                        for keyword in keywords
                    )
                )
                self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0)
                self.assertEqual(descriptor["required_capabilities"], ["expert.invoke"])

                reloaded = _load_product(package, module_name, "reload")
                reloaded_plugin = getattr(
                    reloaded, f"Zara{class_name}ExpertPlugin"
                )()
                self.assertEqual(reloaded_plugin.descriptor(), descriptor_text)


if __name__ == "__main__":
    unittest.main()
