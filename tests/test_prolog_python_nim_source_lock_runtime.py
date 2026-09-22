from __future__ import annotations

from dataclasses import replace
import importlib.util
import json
from pathlib import Path
import shutil
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


CASES = {
    "prolog": ("zara-prolog-expert", "zara_prolog_expert", "Prolog"),
    "python": ("zara-python-expert", "zara_python_expert", "Python"),
    "nim": ("zara-nim-expert", "zara_nim_expert", "Nim"),
}


def _install_zara_stubs() -> None:
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
    _install_zara_stubs()
    path = runtime_root / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        f"test_source_lock_runtime_{module_name}_{suffix}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PrologPythonNimSourceLockRuntimeTests(unittest.TestCase):
    def test_good_installed_package_keeps_canonical_zero_model_descriptor(self) -> None:
        host_specs = {spec.key: spec for spec in language_family_module.language_family_specs()}
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for language, (package, module_name, class_name) in CASES.items():
                with self.subTest(language=language):
                    runtime_root = _install_package(root / language, package, module_name)
                    module = _load_plugin(runtime_root, module_name, "good")
                    plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
                    descriptor = json.loads(plugin.descriptor())
                    self.assertEqual(descriptor["expert_id"], host_specs[language].expert_id)
                    self.assertEqual(
                        descriptor["source_reference"],
                        host_specs[language].source_reference,
                    )
                    self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0)

    def test_installed_package_rejects_source_lock_byte_drift_after_reload(self) -> None:
        """The installed lock is authority, not documentation beside plugin.py."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for language, (package, module_name, class_name) in CASES.items():
                with self.subTest(language=language):
                    runtime_root = _install_package(root / language, package, module_name)
                    original = _load_plugin(runtime_root, module_name, "before_drift")
                    original_plugin = getattr(original, f"Zara{class_name}ExpertPlugin")()
                    self.assertEqual(
                        json.loads(original_plugin.descriptor())["resource_limits"]["max_model_calls"],
                        0,
                    )

                    lock_path = runtime_root / "expert-source.lock.json"
                    lock = json.loads(lock_path.read_text(encoding="utf-8"))
                    lock["canonical_source"]["commit"] = "0" * 40
                    lock_path.write_text(
                        json.dumps(lock, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )

                    reloaded = _load_plugin(runtime_root, module_name, "after_drift")
                    plugin = getattr(reloaded, f"Zara{class_name}ExpertPlugin")()
                    error_class = getattr(reloaded, f"{class_name}ExpertAdapterError")
                    with self.assertRaisesRegex(error_class, "source-lock"):
                        plugin.descriptor()

    def test_descriptor_rejects_host_language_spec_drift(self) -> None:
        """Product projection must not outlive the canonical zara-expert identity."""
        original_specs = language_family_module.language_family_specs()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for language, (package, module_name, class_name) in CASES.items():
                with self.subTest(language=language):
                    runtime_root = _install_package(root / language, package, module_name)
                    drifted_specs = tuple(
                        replace(
                            spec,
                            source_reference=f"dotfiles:.zara/experts/{language}-drift",
                        )
                        if spec.key == language
                        else spec
                        for spec in original_specs
                    )
                    with mock.patch.object(language_family_module, "_SPECS", drifted_specs):
                        reloaded = _load_plugin(runtime_root, module_name, "host_drift")
                        plugin = getattr(reloaded, f"Zara{class_name}ExpertPlugin")()
                        error_class = getattr(reloaded, f"{class_name}ExpertAdapterError")
                        with self.assertRaisesRegex(error_class, "source-lock"):
                            plugin.descriptor()


if __name__ == "__main__":
    unittest.main()
