from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest


ROOT = Path(__file__).resolve().parents[1]
REQUEST_ID = "request-source-lock"
ACTIVATION_ID = "act:0123456789abcdef0123456789abcdef"
EXPECTED_REGISTRY_GENERATION = 7
EXPECTED_RUNTIME_GENERATION = 11

CASES = {
    "javascript": (
        "zara-javascript-expert",
        "zara_javascript_expert",
        "JavaScript",
        "inspect",
        {"source": "const x = 1;", "source_generation": "source:1"},
    ),
    "typescript": (
        "zara-typescript-expert",
        "zara_typescript_expert",
        "TypeScript",
        "inspect",
        {"source": "const x: number = 1;", "source_generation": "source:1"},
    ),
    "java": (
        "zara-java-expert",
        "zara_java_expert",
        "Java",
        "inspect",
        {"source": "final class X {}", "source_generation": "source:1"},
    ),
    "kotlin": (
        "zara-kotlin-expert",
        "zara_kotlin_expert",
        "Kotlin",
        "inspect",
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


def _install_package(root: Path, package: str, module_name: str) -> Path:
    source_root = ROOT / "plugins" / package
    runtime_root = root / "share" / "zara" / "runtime" / package
    module_root = runtime_root / "lib" / module_name
    module_root.mkdir(parents=True)
    shutil.copy2(source_root / "expert-source.lock.json", runtime_root / "expert-source.lock.json")
    shutil.copy2(source_root / "lib" / module_name / "plugin.py", module_root / "plugin.py")
    return runtime_root


def _load_plugin(runtime_root: Path, module_name: str, suffix: str):
    _install_zara_stub()
    path = runtime_root / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        f"test_four_language_source_lock_{module_name}_{suffix}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _drift_lock(runtime_root: Path) -> None:
    lock_path = runtime_root / "expert-source.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    lock["canonical_source"]["commit"] = "0" * 40
    lock_path.write_text(
        json.dumps(lock, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class NoDispatchRuntime:
    def __init__(self) -> None:
        self.resolve_calls = 0
        self.invoke_calls = 0

    def resolve_capability(self, capability: str):
        self.resolve_calls += 1
        raise AssertionError(f"source-lock drift reached capability resolution: {capability}")

    def invoke_capability(self, handle, request):
        del handle, request
        self.invoke_calls += 1
        raise AssertionError("source-lock drift reached canonical host invocation")


class FourLanguageSourceLockRuntimeTests(unittest.TestCase):
    def test_installed_package_rejects_source_lock_byte_drift_after_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for language, (package, module_name, class_name, _operation, _payload) in CASES.items():
                with self.subTest(language=language):
                    runtime_root = _install_package(root / language, package, module_name)
                    original = _load_plugin(runtime_root, module_name, "before_drift")
                    original_plugin = getattr(original, f"Zara{class_name}ExpertPlugin")()
                    self.assertEqual(
                        json.loads(original_plugin.descriptor())["resource_limits"]["max_model_calls"],
                        0,
                    )

                    _drift_lock(runtime_root)
                    reloaded = _load_plugin(runtime_root, module_name, "after_drift")
                    plugin = getattr(reloaded, f"Zara{class_name}ExpertPlugin")()
                    error_class = getattr(reloaded, f"{class_name}ExpertAdapterError")
                    with self.assertRaisesRegex(error_class, "source-lock"):
                        plugin.descriptor()

    def test_invoke_revalidates_source_lock_before_host_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for language, (package, module_name, class_name, operation, payload) in CASES.items():
                with self.subTest(language=language):
                    runtime_root = _install_package(root / language, package, module_name)
                    _drift_lock(runtime_root)
                    module = _load_plugin(runtime_root, module_name, "invoke_drift")
                    plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
                    error_class = getattr(module, f"{class_name}ExpertAdapterError")
                    runtime = NoDispatchRuntime()
                    plugin.start(runtime)

                    with self.assertRaisesRegex(error_class, "source-lock"):
                        plugin.invoke(
                            REQUEST_ID,
                            ACTIVATION_ID,
                            operation,
                            EXPECTED_REGISTRY_GENERATION,
                            EXPECTED_RUNTIME_GENERATION,
                            json.dumps(payload),
                        )

                    self.assertEqual(runtime.resolve_calls, 0)
                    self.assertEqual(runtime.invoke_calls, 0)


if __name__ == "__main__":
    unittest.main()
