from __future__ import annotations

import ast
import json
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANONICAL_OPERATIONS = {"match", "inspect", "diagnose", "repair.preview", "repair.verify", "style.rules", "explain"}
CASES = {
    "javascript": {"package":"zara-javascript-expert","module":"zara_javascript_expert","expert_id":"zara:expert/javascript","upstream":"lost-rob0t/prolog-rlm#500","source_reference":"source:dotfiles.javascript-expert","canonical_path":".zara/experts/javascript","extensions":(".js",".jsx",".mjs",".cjs"),"required_topics":{"jsx"},"forbidden_topics":{"types","coroutines"},"jvm":False},
    "typescript": {"package":"zara-typescript-expert","module":"zara_typescript_expert","expert_id":"zara:expert/typescript","upstream":"lost-rob0t/prolog-rlm#500","source_reference":"source:dotfiles.typescript-expert","canonical_path":".zara/experts/typescript","extensions":(".ts",".tsx",".mts",".cts"),"required_topics":{"tsx","types"},"forbidden_topics":{"jsx","coroutines"},"jvm":False},
    "java": {"package":"zara-java-expert","module":"zara_java_expert","expert_id":"zara:expert/java","upstream":"lost-rob0t/prolog-rlm#501","source_reference":"source:dotfiles.java-expert","canonical_path":".zara/experts/java","extensions":(".java",),"required_topics":{"jvm","gradle","android-project-metadata"},"forbidden_topics":{"coroutines","tsx","jsx"},"jvm":True},
    "kotlin": {"package":"zara-kotlin-expert","module":"zara_kotlin_expert","expert_id":"zara:expert/kotlin","upstream":"lost-rob0t/prolog-rlm#501","source_reference":"source:dotfiles.kotlin-expert","canonical_path":".zara/experts/kotlin","extensions":(".kt",".kts"),"required_topics":{"coroutines","jvm","gradle","android-project-metadata"},"forbidden_topics":{"tsx","jsx"},"jvm":True},
}
AUTHORITY_SHAPED_FIELDS={"argv","command","capability","approval","tool","provider","model"}


def _constants(package: str, module: str) -> dict[str, object]:
    path=ROOT / "plugins" / package / "lib" / module / "plugin.py"
    tree=ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values={}
    for node in tree.body:
        if isinstance(node,ast.Assign) and len(node.targets)==1: target=node.targets[0]; value=node.value
        elif isinstance(node,ast.AnnAssign): target=node.target; value=node.value
        else: continue
        if not isinstance(target,ast.Name) or value is None: continue
        try: values[target.id]=ast.literal_eval(value)
        except (TypeError,ValueError): continue
    return values


def _field_names(operation_fields):
    return {str(field["name"]) for fields in operation_fields.values() for field in fields}


class ExpertFactoryLanguageContractTests(unittest.TestCase):
    def test_all_four_adapters_consume_the_same_canonical_host_operation_abi(self):
        for language,case in CASES.items():
            constants=_constants(case["package"],case["module"])
            self.assertEqual(set(constants["OPERATION_FIELDS"]),CANONICAL_OPERATIONS,language)
            self.assertEqual(constants["EXPERT_ID"],case["expert_id"],language)
            self.assertEqual(constants["UPSTREAM_CONTRACT"],case["upstream"],language)
            self.assertEqual(constants["SOURCE_REFERENCE"],case["source_reference"],language)
            self.assertEqual(constants["HOST_CAPABILITY"],"expert.invoke",language)
            self.assertTrue(AUTHORITY_SHAPED_FIELDS.isdisjoint(_field_names(constants["OPERATION_FIELDS"])),language)

    def test_language_distinctions_are_evidence_boundaries_not_protocol_forks(self):
        boundaries={language:_constants(case["package"],case["module"])["LANGUAGE_BOUNDARIES"] for language,case in CASES.items()}
        for language,case in CASES.items():
            boundary=boundaries[language]
            self.assertEqual(tuple(boundary["extensions"]),case["extensions"],language)
            topics=set(boundary["evidence_topics"])
            self.assertTrue(case["required_topics"] <= topics,language)
            self.assertTrue(case["forbidden_topics"].isdisjoint(topics),language)
            if case["jvm"]:
                self.assertEqual(boundary["project_metadata_policy"],"observation_only",language)
                self.assertTrue(boundary["jvm_project_metadata"],language)
                self.assertTrue(boundary["gradle_project_metadata"],language)
                self.assertTrue(boundary["android_project_metadata"],language)
            else:
                self.assertEqual(boundary["project_metadata_policy"],"not_applicable",language)
                self.assertFalse(boundary["jvm_project_metadata"],language)
                self.assertFalse(boundary["gradle_project_metadata"],language)
                self.assertFalse(boundary["android_project_metadata"],language)
        self.assertTrue(set(boundaries["javascript"]["extensions"]).isdisjoint(boundaries["typescript"]["extensions"]))
        self.assertTrue(set(boundaries["java"]["extensions"]).isdisjoint(boundaries["kotlin"]["extensions"]))

    def test_source_locks_bind_exact_upstream_contract_and_canonical_brain(self):
        for language,case in CASES.items():
            lock=json.loads((ROOT / "plugins" / case["package"] / "expert-source.lock.json").read_text(encoding="utf-8"))
            self.assertEqual(lock["expert_id"],case["expert_id"],language)
            self.assertEqual(lock["canonical_source"]["repository"],"lost-rob0t/dotfiles",language)
            self.assertEqual(lock["canonical_source"]["path"],case["canonical_path"],language)
            self.assertEqual(f"lost-rob0t/prolog-rlm#{lock['runtime_contract']['issue']}",case["upstream"],language)
            self.assertEqual(lock["zara_contract"]["issue"],1233,language)
            self.assertEqual(lock["zara_contract"]["schema_pr"],1273,language)


if __name__ == "__main__": unittest.main()
