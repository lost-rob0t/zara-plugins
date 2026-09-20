from __future__ import annotations

import ast
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADAPTERS = (
    (
        REPO_ROOT / "plugins" / "zara-nix-expert" / "lib" / "zara_nix_expert" / "plugin.py",
        "ZaraNixExpertPlugin",
    ),
    (
        REPO_ROOT / "plugins" / "zara-bash-expert" / "lib" / "zara_bash_expert" / "plugin.py",
        "ZaraBashExpertPlugin",
    ),
)


class NixBashNoParallelToolSurfaceTests(unittest.TestCase):
    def test_raw_adapter_classes_expose_no_parallel_expert_tools(self) -> None:
        # Keep this gate dependency-free so it runs before Zara/plugin packages
        # are installed. The lower-level modules are importable Python and must
        # never grow a second descriptor/invoke tool namespace around Core.
        for path, class_name in ADAPTERS:
            with self.subTest(adapter=class_name):
                source = path.read_text(encoding="utf-8")
                self.assertNotIn("StructuredTool.from_function", source)
                module = ast.parse(source, filename=str(path))
                class_node = next(
                    node
                    for node in module.body
                    if isinstance(node, ast.ClassDef) and node.name == class_name
                )
                tools = next(
                    node
                    for node in class_node.body
                    if isinstance(node, ast.FunctionDef) and node.name == "tools"
                )
                returns = [node for node in tools.body if isinstance(node, ast.Return)]
                self.assertEqual(len(returns), 1)
                value = returns[0].value
                self.assertIsInstance(value, ast.Tuple)
                self.assertEqual(value.elts, [])


if __name__ == "__main__":
    unittest.main()
