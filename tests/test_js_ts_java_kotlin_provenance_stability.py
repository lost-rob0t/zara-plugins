from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
HOST_LIB = ROOT / "plugins" / "zara-expert" / "lib"
if str(HOST_LIB) not in sys.path:
    sys.path.insert(0, str(HOST_LIB))

from zara_expert import language_family as language_family_module

ACTIVATION_ID = "act:" + "a" * 32
INVOCATION_ID = "inv:" + "b" * 32
CASES = {
    "javascript": (
        "zara-javascript-expert",
        "zara_javascript_expert",
        "JavaScript",
        {"source": "const x = 1;", "source_generation": "source:1"},
    ),
    "typescript": (
        "zara-typescript-expert",
        "zara_typescript_expert",
        "TypeScript",
        {"source": "const x: number = 1;", "source_generation": "source:1"},
    ),
    "java": (
        "zara-java-expert",
        "zara_java_expert",
        "Java",
        {"source": "final class X {}", "source_generation": "source:1"},
    ),
    "kotlin": (
        "zara-kotlin-expert",
        "zara_kotlin_expert",
        "Kotlin",
        {"source": "class X", "source_generation": "source:1"},
    ),
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
    sys.modules["zara"] = zara
    sys.modules["zara.plugins"] = plugins


def _load_plugin(package: str, module_name: str, suffix: str):
    _install_zara_stub()
    path = ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        f"test_four_language_provenance_{module_name}_{suffix}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MutationRuntime:
    def __init__(self, module, before_result):
        self.module = module
        self.before_result = before_result
        self.requests: list[dict[str, object]] = []

    def resolve_capability(self, capability):
        if capability != "expert.invoke":
            raise AssertionError(capability)
        return object()

    def invoke_capability(self, _handle, request):
        self.requests.append(request)
        self.before_result()
        return {
            "protocol": self.module.PROTOCOL,
            "request_id": request["request_id"],
            "invocation_id": INVOCATION_ID,
            "activation_id": request["activation_id"],
            "expert_id": request["expert_id"],
            "expert_version": self.module.PLUGIN_VERSION,
            "manifest_digest": self.module.MANIFEST_DIGEST,
            "expert_operation": request["expert_operation"],
            "resolved_registry_generation": request["expected_registry_generation"],
            "resolved_runtime_generation": request["expected_runtime_generation"],
            "verdict": "succeeded",
            "data": {"result": {"language": self.module.EXPERT_ID.rsplit("/", 1)[-1]}},
            "evidence_refs": ["fixture:provenance-stability"],
            "usage": {"model_calls": 0},
            "effect_receipts": [],
        }


class FourLanguageProvenanceStabilityTests(unittest.TestCase):
    def test_source_lock_cannot_change_during_canonical_host_invocation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for language, (package, module_name, class_name, payload) in CASES.items():
                with self.subTest(language=language):
                    module = _load_plugin(package, module_name, "lock-drift")
                    error_class = getattr(module, f"{class_name}ExpertAdapterError")
                    raw = (ROOT / "plugins" / package / "expert-source.lock.json").read_bytes()
                    lock_path = root / f"{language}-expert-source.lock.json"
                    lock_path.write_bytes(raw)
                    runtime = MutationRuntime(
                        module,
                        lambda: lock_path.write_bytes(raw + b"\n"),
                    )
                    plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
                    plugin.start(runtime)
                    with (
                        mock.patch.object(module, "_source_lock_path", return_value=lock_path),
                        self.assertRaisesRegex(error_class, "source-lock"),
                    ):
                        plugin.invoke(
                            f"request-{language}-lock-drift",
                            ACTIVATION_ID,
                            "inspect",
                            7,
                            11,
                            json.dumps(payload),
                        )
                    self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)

    def test_host_identity_cannot_change_during_canonical_host_invocation(self) -> None:
        canonical_specs = language_family_module.language_family_specs()
        for language, (package, module_name, class_name, payload) in CASES.items():
            with self.subTest(language=language):
                module = _load_plugin(package, module_name, "host-drift")
                error_class = getattr(module, f"{class_name}ExpertAdapterError")
                drifted_specs = tuple(
                    replace(spec, source_reference=spec.source_reference + "-drift")
                    if spec.key == language
                    else spec
                    for spec in canonical_specs
                )
                state = {"drifted": False}

                def specs():
                    return drifted_specs if state["drifted"] else canonical_specs

                def drift_host() -> None:
                    state["drifted"] = True

                runtime = MutationRuntime(module, drift_host)
                plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
                plugin.start(runtime)
                with (
                    mock.patch.object(
                        language_family_module,
                        "language_family_specs",
                        side_effect=specs,
                    ),
                    self.assertRaisesRegex(error_class, "source-lock-host"),
                ):
                    plugin.invoke(
                        f"request-{language}-host-drift",
                        ACTIVATION_ID,
                        "inspect",
                        7,
                        11,
                        json.dumps(payload),
                    )
                self.assertEqual(runtime.requests[0]["limits"]["max_model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
