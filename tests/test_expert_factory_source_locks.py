from __future__ import annotations

import ast
import json
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGES = {
    "javascript": {
        "package": "zara-javascript-expert",
        "module": "zara_javascript_expert",
        "expert_id": "zara:expert/javascript",
        "source_path": ".zara/experts/javascript",
        "runtime_issue": 500,
    },
    "typescript": {
        "package": "zara-typescript-expert",
        "module": "zara_typescript_expert",
        "expert_id": "zara:expert/typescript",
        "source_path": ".zara/experts/typescript",
        "runtime_issue": 500,
    },
    "java": {
        "package": "zara-java-expert",
        "module": "zara_java_expert",
        "expert_id": "zara:expert/java",
        "source_path": ".zara/experts/java",
        "runtime_issue": 501,
    },
    "kotlin": {
        "package": "zara-kotlin-expert",
        "module": "zara_kotlin_expert",
        "expert_id": "zara:expert/kotlin",
        "source_path": ".zara/experts/kotlin",
        "runtime_issue": 501,
    },
}


def _constants(path: pathlib.Path) -> dict[str, object]:
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
        except (ValueError, TypeError):
            continue
    return values


class ExpertFactorySourceLockTests(unittest.TestCase):
    def test_source_locks_bind_product_adapters_to_canonical_owners(self) -> None:
        for language, expected in PACKAGES.items():
            package_root = ROOT / "plugins" / str(expected["package"])
            lock = json.loads((package_root / "expert-source.lock.json").read_text(encoding="utf-8"))
            constants = _constants(package_root / "lib" / str(expected["module"]) / "plugin.py")

            self.assertEqual(lock["schema_version"], 1, language)
            self.assertEqual(lock["expert_id"], expected["expert_id"], language)
            self.assertEqual(lock["expert_id"], constants["EXPERT_ID"], language)
            self.assertEqual(lock["adapter_version"], constants["PLUGIN_VERSION"], language)

            self.assertEqual(lock["canonical_source"], {
                "repository": "lost-rob0t/dotfiles",
                "path": expected["source_path"],
                "issue": 292,
            }, language)
            self.assertEqual(lock["runtime_contract"], {
                "repository": "lost-rob0t/prolog-rlm",
                "issue": expected["runtime_issue"],
            }, language)
            self.assertEqual(
                constants["UPSTREAM_CONTRACT"],
                f"lost-rob0t/prolog-rlm#{expected['runtime_issue']}",
                language,
            )
            self.assertEqual(lock["zara_contract"], {
                "repository": "lost-rob0t/zara",
                "issue": 1233,
                "schema_pr": 1273,
            }, language)

    def test_language_pairs_do_not_collapse_to_one_canonical_source(self) -> None:
        locks = {
            language: json.loads(
                (ROOT / "plugins" / str(expected["package"]) / "expert-source.lock.json").read_text(encoding="utf-8")
            )
            for language, expected in PACKAGES.items()
        }
        self.assertNotEqual(locks["javascript"]["canonical_source"]["path"], locks["typescript"]["canonical_source"]["path"])
        self.assertNotEqual(locks["java"]["canonical_source"]["path"], locks["kotlin"]["canonical_source"]["path"])
        self.assertEqual(locks["javascript"]["runtime_contract"], locks["typescript"]["runtime_contract"])
        self.assertEqual(locks["java"]["runtime_contract"], locks["kotlin"]["runtime_contract"])


if __name__ == "__main__":
    unittest.main()
