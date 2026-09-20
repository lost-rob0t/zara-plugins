from __future__ import annotations

import ast
import importlib.util
import pathlib
import sys
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGES = {
    "javascript": ("zara-javascript-expert", "zara_javascript_expert", "ZaraJavaScriptExpertPlugin"),
    "typescript": ("zara-typescript-expert", "zara_typescript_expert", "ZaraTypeScriptExpertPlugin"),
    "java": ("zara-java-expert", "zara_java_expert", "ZaraJavaExpertPlugin"),
    "kotlin": ("zara-kotlin-expert", "zara_kotlin_expert", "ZaraKotlinExpertPlugin"),
}


def _install_zara_stub() -> None:
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
    sys.modules.setdefault("zara", zara)
    sys.modules.setdefault("zara.plugins", plugins)


def _load_plugin(package: str, module_name: str):
    _install_zara_stub()
    path = ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(f"canonical_tool_boundary_{module_name}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


class CanonicalToolBoundaryTests(unittest.TestCase):
    def test_adapters_do_not_import_or_publish_parallel_structured_tools(self) -> None:
        for language, (package, module_name, _) in PACKAGES.items():
            with self.subTest(language=language):
                module, path = _load_plugin(package, module_name)
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                imported = set()
                for node in ast.walk(tree):
                    if isinstance(node, ast.Import):
                        imported.update(alias.name for alias in node.names)
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported.add(node.module)
                self.assertFalse(
                    any(name == "langchain_core" or name.startswith("langchain_core.") for name in imported),
                    f"{language}: adapter-local StructuredTool imports bypass Zara Core expert authority",
                )
                plugin = module.create_plugin()
                self.assertEqual(
                    plugin.tools(),
                    (),
                    f"{language}: ZARA-EXPERT/1 activation/invocation must stay on the canonical Core boundary",
                )

    def test_package_roots_do_not_export_low_level_adapter_classes(self) -> None:
        for language, (package, module_name, private_class) in PACKAGES.items():
            with self.subTest(language=language):
                init_path = ROOT / "plugins" / package / "lib" / module_name / "__init__.py"
                tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
                imported_names = {
                    alias.name
                    for node in ast.walk(tree)
                    if isinstance(node, ast.ImportFrom)
                    for alias in node.names
                }
                exported_names: set[str] = set()
                for node in tree.body:
                    if not isinstance(node, ast.Assign):
                        continue
                    if not any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets):
                        continue
                    if isinstance(node.value, (ast.List, ast.Tuple)):
                        exported_names.update(
                            element.value
                            for element in node.value.elts
                            if isinstance(element, ast.Constant) and isinstance(element.value, str)
                        )
                self.assertNotIn(private_class, imported_names, language)
                self.assertNotIn(private_class, exported_names, language)
                self.assertIn("create_plugin", imported_names, language)
                self.assertIn("create_plugin", exported_names, language)


if __name__ == "__main__":
    unittest.main()
