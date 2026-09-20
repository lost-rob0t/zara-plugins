from __future__ import annotations

import ast
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOST = ROOT / "plugins" / "zara-expert" / "lib" / "zara_expert" / "language_family.py"
ADAPTERS = {
    "javascript": ROOT / "plugins" / "zara-javascript-expert" / "lib" / "zara_javascript_expert" / "plugin.py",
    "typescript": ROOT / "plugins" / "zara-typescript-expert" / "lib" / "zara_typescript_expert" / "plugin.py",
    "java": ROOT / "plugins" / "zara-java-expert" / "lib" / "zara_java_expert" / "plugin.py",
    "kotlin": ROOT / "plugins" / "zara-kotlin-expert" / "lib" / "zara_kotlin_expert" / "plugin.py",
}
REQUIRED_READ_ONLY_OPERATIONS = {
    "match",
    "inspect",
    "diagnose",
    "repair.verify",
    "style.rules",
    "explain",
}


def _assigned_dict_keys(path: Path, name: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            raise AssertionError(f"{path}: {name} must remain a literal dict for contract inspection")
        keys: set[str] = set()
        for key in value.keys:
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                raise AssertionError(f"{path}: {name} keys must remain literal strings")
            keys.add(key.value)
        return keys
    raise AssertionError(f"{path}: missing {name}")


class CanonicalLanguageHostAbiTests(unittest.TestCase):
    def test_product_adapters_do_not_invent_a_second_language_operation_abi(self):
        host_operations = _assigned_dict_keys(HOST, "_OPERATION_BINDINGS") | {"repair.apply"}
        self.assertTrue(REQUIRED_READ_ONLY_OPERATIONS <= host_operations)

        for language, path in ADAPTERS.items():
            with self.subTest(language=language):
                adapter_operations = _assigned_dict_keys(path, "OPERATION_FIELDS")
                unknown = adapter_operations - host_operations
                self.assertEqual(
                    unknown,
                    set(),
                    f"{language} adapter invents operation ids outside the landed zara-expert "
                    f"registered-predicate host ABI: {sorted(unknown)}; product-specific parser, "
                    "type, JVM, Gradle, Android, JSX, and coroutine distinctions belong in the "
                    "canonical brain/evidence inputs, not a competing invocation protocol",
                )
                self.assertTrue(
                    REQUIRED_READ_ONLY_OPERATIONS <= adapter_operations,
                    f"{language} adapter must expose the shared read-only language operation set",
                )
                self.assertNotIn(
                    "repair.apply",
                    adapter_operations,
                    f"{language} adapter must not gain write authority; repair.apply stays on Zara Core",
                )


if __name__ == "__main__":
    unittest.main()
