from __future__ import annotations

import ast
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]

CASES = {
    "javascript": {
        "package": "zara-javascript-expert",
        "module": "zara_javascript_expert",
        "expert_id": "zara:expert/javascript",
        "upstream": "lost-rob0t/prolog-rlm#500",
        "source_reference": "source:dotfiles.javascript-expert",
        "canonical_path": ".zara/experts/javascript",
        "required_operations": {"parse", "inspect_module", "inspect_jsx", "diagnose", "style", "repair_verify"},
        "forbidden_operations": {"inspect_tsx", "typecheck", "inspect_jvm_project", "inspect_coroutines", "compile_check"},
        "jvm_metadata": False,
    },
    "typescript": {
        "package": "zara-typescript-expert",
        "module": "zara_typescript_expert",
        "expert_id": "zara:expert/typescript",
        "upstream": "lost-rob0t/prolog-rlm#500",
        "source_reference": "source:dotfiles.typescript-expert",
        "canonical_path": ".zara/experts/typescript",
        "required_operations": {"parse", "inspect_module", "inspect_tsx", "typecheck", "diagnose", "style", "repair_verify"},
        "forbidden_operations": {"inspect_jsx", "inspect_jvm_project", "inspect_coroutines", "compile_check"},
        "jvm_metadata": False,
    },
    "java": {
        "package": "zara-java-expert",
        "module": "zara_java_expert",
        "expert_id": "zara:expert/java",
        "upstream": "lost-rob0t/prolog-rlm#501",
        "source_reference": "source:dotfiles.java-expert",
        "canonical_path": ".zara/experts/java",
        "required_operations": {"parse", "inspect_jvm_project", "compile_check", "diagnose", "style", "repair_verify"},
        "forbidden_operations": {"inspect_jsx", "inspect_tsx", "typecheck", "inspect_coroutines"},
        "jvm_metadata": True,
    },
    "kotlin": {
        "package": "zara-kotlin-expert",
        "module": "zara_kotlin_expert",
        "expert_id": "zara:expert/kotlin",
        "upstream": "lost-rob0t/prolog-rlm#501",
        "source_reference": "source:dotfiles.kotlin-expert",
        "canonical_path": ".zara/experts/kotlin",
        "required_operations": {"parse", "inspect_jvm_project", "inspect_coroutines", "compile_check", "diagnose", "style", "repair_verify"},
        "forbidden_operations": {"inspect_jsx", "inspect_tsx", "typecheck"},
        "jvm_metadata": True,
    },
}

AUTHORITY_SHAPED_FIELDS = {
    "argv",
    "command",
    "capability",
    "approval",
    "tool",
    "provider",
    "model",
}
JVM_METADATA_FIELDS = {
    "jvm_project_metadata",
    "gradle_project_metadata",
    "android_project_metadata",
}


def _constants(package: str, module: str) -> dict[str, object]:
    path = ROOT / "plugins" / package / "lib" / module / "plugin.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, object] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        try:
            values[target.id] = ast.literal_eval(node.value)
        except (TypeError, ValueError):
            continue
    return values


def _field_names(operation_fields: dict[str, tuple[dict[str, object], ...]]) -> set[str]:
    return {
        str(field["name"])
        for fields in operation_fields.values()
        for field in fields
    }


class ExpertFactoryLanguageContractTests(unittest.TestCase):
    def test_distinct_language_operation_surfaces_are_pinned(self) -> None:
        for language, case in CASES.items():
            constants = _constants(case["package"], case["module"])
            operations = set(constants["OPERATION_FIELDS"])
            self.assertTrue(case["required_operations"] <= operations, language)
            self.assertTrue(case["forbidden_operations"].isdisjoint(operations), language)
            self.assertEqual(constants["EXPERT_ID"], case["expert_id"], language)
            self.assertEqual(constants["UPSTREAM_CONTRACT"], case["upstream"], language)
            self.assertEqual(constants["SOURCE_REFERENCE"], case["source_reference"], language)
            self.assertEqual(constants["HOST_CAPABILITY"], "expert.invoke", language)

    def test_project_metadata_is_observation_only_and_language_scoped(self) -> None:
        for language, case in CASES.items():
            constants = _constants(case["package"], case["module"])
            operation_fields = constants["OPERATION_FIELDS"]
            names = _field_names(operation_fields)
            self.assertTrue(AUTHORITY_SHAPED_FIELDS.isdisjoint(names), language)

            if case["jvm_metadata"]:
                self.assertTrue(JVM_METADATA_FIELDS <= names, language)
                self.assertNotIn("project_metadata", names, language)
                inspect_fields = {
                    field["name"]: field
                    for field in operation_fields["inspect_jvm_project"]
                }
                self.assertTrue(inspect_fields["jvm_project_metadata"]["required"], language)
                for name in JVM_METADATA_FIELDS:
                    self.assertEqual(inspect_fields.get(name, {"type": "object"})["type"], "object", language)
            else:
                self.assertTrue(JVM_METADATA_FIELDS.isdisjoint(names), language)

    def test_source_locks_bind_exact_upstream_contract_and_canonical_brain(self) -> None:
        for language, case in CASES.items():
            lock_path = ROOT / "plugins" / case["package"] / "expert-source.lock.json"
            lock = json.loads(lock_path.read_text(encoding="utf-8"))
            self.assertEqual(lock["expert_id"], case["expert_id"], language)
            self.assertEqual(lock["canonical_source"]["repository"], "lost-rob0t/dotfiles", language)
            self.assertEqual(lock["canonical_source"]["path"], case["canonical_path"], language)
            self.assertEqual(lock["runtime_contract"]["repository"], "lost-rob0t/prolog-rlm", language)
            self.assertEqual(
                f"lost-rob0t/prolog-rlm#{lock['runtime_contract']['issue']}",
                case["upstream"],
                language,
            )


if __name__ == "__main__":
    unittest.main()
