from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
EXPECTED_DOTFILES_COMMIT = "97534b85f96a5ae7962762268440fb9ae7815ae0"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"
ACTIVATION_ID = "act:" + "4" * 32
REGISTRY_GENERATION = 17
RUNTIME_GENERATION = 29
PACKAGES = {
    "javascript": ("zara-javascript-expert", "zara_javascript_expert", "JavaScript"),
    "typescript": ("zara-typescript-expert", "zara_typescript_expert", "TypeScript"),
    "java": ("zara-java-expert", "zara_java_expert", "Java"),
    "kotlin": ("zara-kotlin-expert", "zara_kotlin_expert", "Kotlin"),
}
SOURCE = {
    "javascript": "export const answer = 42;",
    "typescript": "export const answer: number = 42;",
    "java": "public final class Answer { static final int VALUE = 42; }",
    "kotlin": "object Answer { const val VALUE: Int = 42 }",
}
PATH = {
    "javascript": "index.js",
    "typescript": "component.tsx",
    "java": "Answer.java",
    "kotlin": "Answer.kt",
}

sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertHost
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.language_source_contract import validate_language_source_contracts


def _run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _checkout_head(root: Path, expected: str) -> None:
    result = _run("git", "rev-parse", "HEAD", cwd=root)
    if result.returncode != 0:
        raise AssertionError(f"cannot resolve Dotfiles checkout: {result.stderr}")
    actual = result.stdout.strip()
    if actual != expected:
        raise AssertionError(
            f"Dotfiles checkout must be exact: expected {expected}, got {actual}"
        )


def _install_zara_stub() -> None:
    plugins = types.ModuleType("zara.plugins")

    class PluginMetadata:
        def __init__(self, **kwargs: object) -> None:
            self.__dict__.update(kwargs)

    class ServicePlugin:
        pass

    plugins.PluginMetadata = PluginMetadata
    plugins.ServicePlugin = ServicePlugin
    zara = types.ModuleType("zara")
    zara.plugins = plugins
    sys.modules.setdefault("zara", zara)
    sys.modules.setdefault("zara.plugins", plugins)


def _load_package(package: str, module_name: str):
    _install_zara_stub()
    path = REPO_ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        f"registered_host_e2e_{module_name}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload(language: str, operation: str) -> dict[str, object]:
    source = SOURCE[language]
    generation = f"generation:{language}:1"
    if operation == "match":
        return {"path": PATH[language], "source_generation": generation}
    if operation in {"inspect", "diagnose"}:
        return {"source": source, "source_generation": generation}
    if operation == "repair.preview":
        return {
            "source": source,
            "source_generation": generation,
            "diagnostic_ref": f"diagnostic:{language}:1",
        }
    if operation == "repair.verify":
        return {
            "original_source": source,
            "candidate_source": source + "\n",
            "source_generation": generation,
        }
    if operation == "style.rules":
        return {"source": source, "project_style": f"project-style:{language}:1"}
    if operation == "explain":
        return {
            "decision_ref": f"decision:{language}:1",
            "source_generation": generation,
        }
    raise AssertionError(f"unknown fixture operation: {operation}")


class RegisteredPredicateRuntime:
    """Test facade for the existing expert.invoke capability over ExpertHost.

    This owns no registry, planner, provider, permission state, or history. It
    merely exposes the package runtime seam and dispatches to the canonical
    zara-expert registered-predicate handler used by the product integration.
    """

    def __init__(self, host: ExpertHost, module: Any) -> None:
        self._module = module
        self._handler = make_language_expert_handler(host, module.EXPERT_ID)
        self.resolved: list[str] = []
        self.requests: list[dict[str, Any]] = []

    def resolve_capability(self, capability: str) -> str:
        if capability != "expert.invoke":
            raise AssertionError(f"unexpected capability: {capability}")
        self.resolved.append(capability)
        return capability

    def invoke_capability(self, handle: str, request: dict[str, Any]) -> dict[str, Any]:
        if handle != "expert.invoke":
            raise AssertionError("package bypassed canonical expert.invoke capability")
        self.requests.append(request)
        result = self._handler(
            expert_operation=request["expert_operation"],
            **request["input"],
        )
        return {
            "protocol": request["protocol"],
            "request_id": request["request_id"],
            "invocation_id": "inv:" + "0" * 32,
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": self._module.PLUGIN_VERSION,
            "manifest_digest": self._module.MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": result["verdict"],
            "data": result["data"],
            "evidence_refs": result["evidence_refs"],
            "usage": result["usage"],
            "effect_receipts": result["effect_receipts"],
        }


def _assert_declared_output(
    case: unittest.TestCase,
    module: Any,
    operation: str,
    data: Mapping[str, object],
) -> None:
    declared = {field["name"]: field for field in module.OPERATION_OUTPUT_FIELDS[operation]}
    case.assertFalse(set(data) - set(declared), (operation, data))
    for name, field in declared.items():
        if field["required"]:
            case.assertIn(name, data, (operation, data))
        if name not in data:
            continue
        value = data[name]
        kind = field["type"]
        if kind == "boolean":
            case.assertIs(type(value), bool, (operation, name, value))
        elif kind == "object":
            case.assertIsInstance(value, Mapping, (operation, name, value))
        elif kind == "list":
            case.assertIsInstance(value, list, (operation, name, value))
        else:
            raise AssertionError(f"unhandled output field type: {kind}")


@unittest.skipUnless(DOTFILES_ROOT, "exact Dotfiles checkout not provided")
class JsTsJavaKotlinRegisteredHostAllOperationsE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for registered-host E2E")
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT)
        cls.sources = {
            language: [
                cls.dotfiles_root
                / ".zara"
                / "experts"
                / language
                / "kb"
                / "expert.pl"
            ]
            for language in PACKAGES
        }
        validate_language_source_contracts(cls.sources)

    def _host(self) -> ExpertHost:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        host = ExpertHost(
            SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
        )
        registered = register_language_family(host, self.sources)
        self.assertEqual(registered, frozenset(PACKAGES))
        available = {
            item["expert_id"]: item["availability"]
            for item in descriptors(registered)
            if item["expert_id"] in {f"zara:expert/{name}" for name in PACKAGES}
        }
        self.assertEqual(set(available.values()), {"available"})
        return host

    def test_all_four_packages_cross_registered_predicates_for_every_declared_operation(self) -> None:
        host = self._host()
        for language, (package, module_name, class_name) in PACKAGES.items():
            module = _load_package(package, module_name)
            runtime = RegisteredPredicateRuntime(host, module)
            plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
            plugin.start(runtime)
            for operation in sorted(module.ALLOWED_OPERATIONS):
                with self.subTest(language=language, operation=operation):
                    result = json.loads(
                        plugin.invoke(
                            f"registered-host-{language}-{operation}",
                            ACTIVATION_ID,
                            operation,
                            REGISTRY_GENERATION,
                            RUNTIME_GENERATION,
                            json.dumps(_payload(language, operation)),
                        )
                    )
                    expected_verdict = "blocked" if operation == "repair.verify" else "succeeded"
                    self.assertEqual(result["verdict"], expected_verdict)
                    self.assertEqual(result["usage"], {"model_calls": 0})
                    self.assertEqual(result["effect_receipts"], [])
                    self.assertTrue(result["evidence_refs"])
                    if operation == "repair.verify":
                        self.assertEqual(result["data"], {})
                    else:
                        _assert_declared_output(self, module, operation, result["data"])

            self.assertEqual(runtime.resolved, ["expert.invoke"] * len(module.ALLOWED_OPERATIONS))
            self.assertTrue(
                all(request["limits"]["max_model_calls"] == 0 for request in runtime.requests)
            )

    def test_operation_projection_preserves_language_and_jvm_android_boundaries(self) -> None:
        host = self._host()
        projections: dict[str, dict[str, object]] = {}
        for language, (package, module_name, class_name) in PACKAGES.items():
            module = _load_package(package, module_name)
            runtime = RegisteredPredicateRuntime(host, module)
            plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
            plugin.start(runtime)
            style = json.loads(
                plugin.invoke(
                    f"style-{language}",
                    ACTIVATION_ID,
                    "style.rules",
                    REGISTRY_GENERATION,
                    RUNTIME_GENERATION,
                    json.dumps(_payload(language, "style.rules")),
                )
            )
            projections[language] = style["data"]

        js_rules = "\n".join(map(str, projections["javascript"]["style_rules"]))
        ts_rules = "\n".join(map(str, projections["typescript"]["style_rules"]))
        java_rules = "\n".join(map(str, projections["java"]["style_rules"]))
        kotlin_rules = "\n".join(map(str, projections["kotlin"]["style_rules"]))
        self.assertIn("no_implicit_typescript_semantics", js_rules)
        self.assertIn("explicit_type_only_imports", ts_rules)
        for jvm_rules in (java_rules, kotlin_rules):
            self.assertIn("gradle_jvm_metadata_observation_only", jvm_rules)
            self.assertIn("android_metadata_observation_only", jvm_rules)
        self.assertNotIn("coroutine", java_rules)
        self.assertIn("coroutine_structure_preserved", kotlin_rules)

        for language in ("java", "kotlin"):
            provenance = "\n".join(map(str, projections[language]["style_provenance"]))
            self.assertIn("dotfiles:.zara/experts/", provenance)


if __name__ == "__main__":
    unittest.main()
