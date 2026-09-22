from __future__ import annotations

import hashlib
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


CASES = {
    "prolog": ("zara-prolog-expert", "zara_prolog_expert", "Prolog"),
    "python": ("zara-python-expert", "zara_python_expert", "Python"),
    "nim": ("zara-nim-expert", "zara_nim_expert", "Nim"),
}


SEMANTIC_MUTATIONS = {
    "unknown-top-level": lambda lock: lock.__setitem__("unexpected_provenance", True),
    "unknown-canonical-source": lambda lock: lock["canonical_source"].__setitem__("unexpected", "x"),
    "unknown-runtime-contract": lambda lock: lock["runtime_contract"].__setitem__("unexpected", "x"),
    "unknown-zara-contract": lambda lock: lock["zara_contract"].__setitem__("unexpected", "x"),
    "canonical-issue": lambda lock: lock["canonical_source"].__setitem__("issue", 999999),
    "canonical-producer-pr": lambda lock: lock["canonical_source"].__setitem__("producer_pr", 999999),
    "zara-repository": lambda lock: lock["zara_contract"].__setitem__("repository", "lost-rob0t/not-zara"),
    "zara-issue": lambda lock: lock["zara_contract"].__setitem__("issue", 999999),
    "zara-schema-pr": lambda lock: lock["zara_contract"].__setitem__("schema_pr", 999999),
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


def _load_plugin(package: str, module_name: str, suffix: str):
    _install_zara_stubs()
    path = ROOT / "plugins" / package / "lib" / module_name / "plugin.py"
    spec = importlib.util.spec_from_file_location(
        f"test_source_lock_semantic_closure_{module_name}_{suffix}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _lock_path(package: str) -> Path:
    return ROOT / "plugins" / package / "expert-source.lock.json"


def _write_lock(root: Path, raw: bytes) -> Path:
    path = root / "expert-source.lock.json"
    path.write_bytes(raw)
    return path


def _digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


class PrologPythonNimSourceLockSemanticClosureTests(unittest.TestCase):
    def test_canonical_source_locks_remain_valid_zero_model_descriptors(self) -> None:
        host_specs = {spec.key: spec for spec in language_family_module.language_family_specs()}
        for language, (package, module_name, class_name) in CASES.items():
            with self.subTest(language=language):
                module = _load_plugin(package, module_name, "good")
                plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
                descriptor = json.loads(plugin.descriptor())
                self.assertEqual(descriptor["expert_id"], host_specs[language].expert_id)
                self.assertEqual(descriptor["source_reference"], host_specs[language].source_reference)
                self.assertEqual(descriptor["resource_limits"]["max_model_calls"], 0)

    def test_source_lock_objects_are_closed_and_semantically_pinned(self) -> None:
        """Digest agreement cannot bless drifted provenance metadata."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for language, (package, module_name, class_name) in CASES.items():
                original = json.loads(_lock_path(package).read_text(encoding="utf-8"))
                for mutation_name, mutate in SEMANTIC_MUTATIONS.items():
                    with self.subTest(language=language, mutation=mutation_name):
                        lock = json.loads(json.dumps(original))
                        mutate(lock)
                        raw = (json.dumps(lock, indent=2, sort_keys=True) + "\n").encode("utf-8")
                        path = _write_lock(root, raw)
                        module = _load_plugin(package, module_name, mutation_name)
                        error_class = getattr(module, f"{class_name}ExpertAdapterError")
                        plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
                        with (
                            mock.patch.object(module, "_source_lock_path", return_value=path),
                            mock.patch.object(module, "MANIFEST_DIGEST", _digest(raw)),
                            self.assertRaisesRegex(error_class, "source-lock"),
                        ):
                            plugin.descriptor()

    def test_duplicate_json_provenance_keys_fail_closed(self) -> None:
        """Canonical source locks must not inherit JSON's last-key-wins ambiguity."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for language, (package, module_name, class_name) in CASES.items():
                with self.subTest(language=language):
                    raw = _lock_path(package).read_bytes()
                    needle = b'  "schema_version": 1,\n'
                    self.assertIn(needle, raw)
                    raw = raw.replace(needle, needle + needle, 1)
                    path = _write_lock(root, raw)
                    module = _load_plugin(package, module_name, "duplicate_key")
                    error_class = getattr(module, f"{class_name}ExpertAdapterError")
                    plugin = getattr(module, f"Zara{class_name}ExpertPlugin")()
                    with (
                        mock.patch.object(module, "_source_lock_path", return_value=path),
                        mock.patch.object(module, "MANIFEST_DIGEST", _digest(raw)),
                        self.assertRaisesRegex(error_class, "source-lock"),
                    ):
                        plugin.descriptor()


if __name__ == "__main__":
    unittest.main()
