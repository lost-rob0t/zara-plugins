from types import SimpleNamespace
import unittest

from scripts.zara_compat import CompatibilityError, require_metadata


class ZaraCompatibilityMetadataDescriptionTest(unittest.TestCase):
    def test_description_mismatch_names_plugin_and_contract(self) -> None:
        entry = {
            "name": "zara-example",
            "version": "1.2.3",
            "api_version": "1",
            "plugin_type": "service",
            "description": "Registry description",
        }
        actual = SimpleNamespace(
            name="zara-example",
            version="1.2.3",
            api_version="1",
            plugin_type="service",
            description="Runtime description",
        )

        with self.assertRaisesRegex(
            CompatibilityError,
            "zara-example.*metadata description.*Registry description.*Runtime description",
        ):
            require_metadata(entry, actual)


if __name__ == "__main__":
    unittest.main()
