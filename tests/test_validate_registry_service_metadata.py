from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "validate-registry.py"
SPEC = importlib.util.spec_from_file_location("validate_registry_service_metadata", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
validate_registry = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validate_registry)


class ServiceMetadataAgreementTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.entrypoint = Path(self.temporary.name) / "entrypoint.py"
        self.entry = {"name": "example", "version": "0.1.0"}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, source: str) -> None:
        self.entrypoint.write_text(source, encoding="utf-8")

    def test_rejects_conflicting_literal_metadata_names(self) -> None:
        self.write(
            "def create_plugin(): return None\n"
            "A = PluginMetadata(name='example', version='0.1.0')\n"
            "B = PluginMetadata(name='other', version='0.1.0')\n"
        )
        with self.assertRaisesRegex(validate_registry.RegistryError, "PluginMetadata name"):
            validate_registry.validate_service_entrypoint(self.entry, self.entrypoint)

    def test_rejects_conflicting_literal_versions(self) -> None:
        self.write(
            "def create_plugin(): return None\n"
            "A = PluginMetadata(name='example', version='0.1.0')\n"
            "B = PluginMetadata(name='example', version='9.9.9')\n"
        )
        with self.assertRaisesRegex(validate_registry.RegistryError, "version"):
            validate_registry.validate_service_entrypoint(self.entry, self.entrypoint)


if __name__ == "__main__":
    unittest.main()
