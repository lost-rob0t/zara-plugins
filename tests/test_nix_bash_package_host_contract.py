"""Keep the Nix/Bash package admission surface on canonical zara-expert operations.

The product packages are adapters to the registered-predicate host.  They must
not publish a second operation vocabulary that the canonical host cannot run.
This contract test intentionally reads the package literals without importing
Zara provider/runtime code, then compares them to zara-expert's single shared
language operation schema.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "zara-expert" / "lib"))

from zara_expert.language_family import language_expert_schemas


PACKAGE_PLUGINS = {
    "nix": ROOT / "plugins" / "zara-nix-expert" / "lib" / "zara_nix_expert" / "plugin.py",
    "bash": ROOT / "plugins" / "zara-bash-expert" / "lib" / "zara_bash_expert" / "plugin.py",
}


def _literal_assignment(path: Path, name: str) -> Any:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in module.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == name and node.value is not None:
                return ast.literal_eval(node.value)
        if isinstance(node, ast.Assign):
            if any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
                return ast.literal_eval(node.value)
    raise AssertionError(f"{path}: missing literal assignment {name}")


class NixBashPackageHostContractTests(unittest.TestCase):
    def test_package_operation_vocabulary_and_inputs_are_canonical_host_contract(self) -> None:
        canonical = language_expert_schemas()
        self.assertTrue(canonical)
        canonical_operations = frozenset(canonical)

        for language, path in PACKAGE_PLUGINS.items():
            with self.subTest(language=language):
                package_fields = _literal_assignment(path, "OPERATION_FIELDS")
                self.assertIs(type(package_fields), dict)
                self.assertEqual(
                    frozenset(package_fields),
                    canonical_operations,
                    (
                        f"{language} package publishes a private operation vocabulary; "
                        "reuse zara_expert.language_family.language_expert_schemas()"
                    ),
                )
                for operation, fields in package_fields.items():
                    self.assertEqual(
                        {"fields": [dict(field) for field in fields]},
                        canonical[operation]["input_schema"],
                        f"{language}:{operation} input schema drifted from canonical host",
                    )

    def test_package_does_not_rename_canonical_operations_before_expert_invoke(self) -> None:
        """The package request must carry the admitted canonical operation unchanged."""
        for language, path in PACKAGE_PLUGINS.items():
            with self.subTest(language=language):
                source = path.read_text(encoding="utf-8")
                self.assertIn('"operation": "expert.invoke"', source)
                self.assertIn('"expert_operation": expert_operation', source)
                self.assertNotIn("LEGACY_OPERATION_MAP", source)


if __name__ == "__main__":
    unittest.main()
