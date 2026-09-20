from __future__ import annotations

import ast
import hashlib
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGES = {
    "javascript": ("zara-javascript-expert", "zara_javascript_expert"),
    "typescript": ("zara-typescript-expert", "zara_typescript_expert"),
    "java": ("zara-java-expert", "zara_java_expert"),
    "kotlin": ("zara-kotlin-expert", "zara_kotlin_expert"),
}


def _manifest_digest(plugin_path: pathlib.Path) -> str:
    tree = ast.parse(plugin_path.read_text(encoding="utf-8"), filename=str(plugin_path))
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name) or target.id != "MANIFEST_DIGEST":
            continue
        try:
            value = ast.literal_eval(node.value)
        except (TypeError, ValueError) as error:
            raise AssertionError("MANIFEST_DIGEST must be a literal immutable source-lock digest") from error
        if not isinstance(value, str):
            raise AssertionError("MANIFEST_DIGEST must be a string")
        return value
    raise AssertionError("MANIFEST_DIGEST literal not found")


class ExpertFactoryManifestSourceBindingTests(unittest.TestCase):
    def test_manifest_digest_pins_exact_canonical_source_lock_bytes(self) -> None:
        for language, (package, module_name) in PACKAGES.items():
            with self.subTest(language=language):
                package_root = ROOT / "plugins" / package
                expected = "sha256:" + hashlib.sha256(
                    (package_root / "expert-source.lock.json").read_bytes()
                ).hexdigest()
                actual = _manifest_digest(
                    package_root / "lib" / module_name / "plugin.py"
                )
                self.assertEqual(
                    actual,
                    expected,
                    f"{language}: activation identity must change when the pinned canonical brain changes",
                )


if __name__ == "__main__":
    unittest.main()
