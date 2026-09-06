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
        self.entry = {"name": "example", "version": "0.1.0", "api_version": "1"}

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write(self, source: str) -> None:
        self.entrypoint.write_text(source, encoding="utf-8")

    def test_rejects_conflicting_literal_metadata_names(self) -> None:
        self.write(
            "def create_plugin(): return None\n"
            "A = PluginMetadata(name='example', version='0.1.0', api_version='1')\n"
            "B = PluginMetadata(name='other', version='0.1.0', api_version='1')\n"
        )
        with self.assertRaisesRegex(validate_registry.RegistryError, "PluginMetadata name"):
            validate_registry.validate_service_entrypoint(self.entry, self.entrypoint)

    def test_rejects_conflicting_literal_versions(self) -> None:
        self.write(
            "def create_plugin(): return None\n"
            "A = PluginMetadata(name='example', version='0.1.0', api_version='1')\n"
            "B = PluginMetadata(name='example', version='9.9.9', api_version='1')\n"
        )
        with self.assertRaisesRegex(validate_registry.RegistryError, "version"):
            validate_registry.validate_service_entrypoint(self.entry, self.entrypoint)

    def test_rejects_conflicting_literal_api_versions(self) -> None:
        self.write(
            "def create_plugin(): return None\n"
            "metadata = PluginMetadata(name='example', version='0.1.0', api_version='2')\n"
        )
        with self.assertRaisesRegex(validate_registry.RegistryError, "api_version"):
            validate_registry.validate_service_entrypoint(self.entry, self.entrypoint)

    def test_accepts_api_version_constant(self) -> None:
        self.write(
            "PLUGIN_VERSION = '0.1.0'\n"
            "API_VERSION = '1'\n"
            "def create_plugin(): return None\n"
            "metadata = PluginMetadata(name='example', version=PLUGIN_VERSION, api_version=API_VERSION)\n"
        )

        validate_registry.validate_service_entrypoint(self.entry, self.entrypoint)

    def test_accepts_plugin_scoped_api_version_constant(self) -> None:
        self.write(
            "EXAMPLE_PLUGIN_VERSION = '0.1.0'\n"
            "EXAMPLE_API_VERSION = '1'\n"
            "def create_plugin(): return None\n"
            "metadata = PluginMetadata(name='example', version=EXAMPLE_PLUGIN_VERSION, api_version=EXAMPLE_API_VERSION)\n"
        )

        validate_registry.validate_service_entrypoint(self.entry, self.entrypoint)


if __name__ == "__main__":
    unittest.main()
