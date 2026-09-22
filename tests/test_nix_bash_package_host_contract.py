"""Keep Nix/Bash product packages on the canonical zara-expert contract.

The product packages are adapters to the registered-predicate host. They must
not publish a second operation vocabulary or descriptor identity that canonical
Core cannot execute. This test reads package literals without importing provider
or runtime code and compares them to zara-expert's single shared language owner.
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "zara-expert" / "lib"))

from zara_expert.language_family import (
    descriptor,
    language_expert_schemas,
    language_family_specs,
)


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


def _canonical_descriptor(language: str) -> dict[str, Any]:
    matches = [spec for spec in language_family_specs() if spec.key == language]
    if len(matches) != 1:
        raise AssertionError(f"expected one canonical {language} expert spec")
    return descriptor(matches[0], available=True)


class NixBashPackageHostContractTests(unittest.TestCase):
    def test_package_descriptor_identity_is_canonical_host_identity(self) -> None:
        for language, path in PACKAGE_PLUGINS.items():
            with self.subTest(language=language):
                canonical = _canonical_descriptor(language)
                self.assertEqual(_literal_assignment(path, "EXPERT_ID"), canonical["expert_id"])
                self.assertEqual(
                    _literal_assignment(path, "PLUGIN_VERSION"),
                    canonical["expert_version"],
                    f"{language} package version identity drifted from canonical host",
                )
                self.assertEqual(
                    _literal_assignment(path, "MANIFEST_DIGEST"),
                    canonical["manifest_digest"],
                    f"{language} package manifest identity drifted from canonical host",
                )
                self.assertEqual(
                    _literal_assignment(path, "SOURCE_REFERENCE"),
                    canonical["source_reference"],
                )

    def test_package_operation_vocabulary_and_schemas_are_canonical_host_contract(self) -> None:
        canonical = language_expert_schemas()
        self.assertTrue(canonical)
        canonical_operations = frozenset(canonical)

        for language, path in PACKAGE_PLUGINS.items():
            with self.subTest(language=language):
                package_inputs = _literal_assignment(path, "OPERATION_FIELDS")
                package_outputs = _literal_assignment(path, "OPERATION_OUTPUT_FIELDS")
                self.assertIs(type(package_inputs), dict)
                self.assertIs(type(package_outputs), dict)
                self.assertEqual(
                    frozenset(package_inputs),
                    canonical_operations,
                    (
                        f"{language} package publishes a private operation vocabulary; "
                        "reuse zara_expert.language_family.language_expert_schemas()"
                    ),
                )
                self.assertEqual(frozenset(package_outputs), canonical_operations)
                for operation in canonical_operations:
                    self.assertEqual(
                        {"fields": [dict(field) for field in package_inputs[operation]]},
                        canonical[operation]["input_schema"],
                        f"{language}:{operation} input schema drifted from canonical host",
                    )
                    self.assertEqual(
                        {"fields": [dict(field) for field in package_outputs[operation]]},
                        canonical[operation]["output_schema"],
                        f"{language}:{operation} output schema drifted from canonical host",
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
