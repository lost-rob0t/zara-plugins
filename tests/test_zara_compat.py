from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from scripts.zara_compat import (
    CompatibilityError,
    load_registry,
    require_metadata,
    validate_zara_source,
)


ROOT = Path(__file__).resolve().parents[1]


class ZaraCompatibilityGateTest(unittest.TestCase):
    def test_registry_enumeration_tracks_every_published_plugin(self) -> None:
        entries = load_registry(ROOT / "plugins.json")
        names = {entry["name"] for entry in entries}

        self.assertIn("zara-agent-zero", names)
        self.assertIn("zara-starintel-server", names)
        self.assertEqual(len(names), len(entries))

    def test_metadata_mismatch_names_the_plugin_and_contract(self) -> None:
        actual = SimpleNamespace(
            name="wrong-name",
            version="9.9.9",
            api_version="1",
            plugin_type="service",
        )

        with self.assertRaisesRegex(
            CompatibilityError,
            "zara-example.*metadata name.*wrong-name",
        ):
            require_metadata(
                {
                    "name": "zara-example",
                    "version": "1.2.3",
                    "api_version": "1",
                    "plugin_type": "service",
                },
                actual,
            )

    def test_zara_source_must_contain_the_real_plugin_api(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(
                CompatibilityError,
                "zara.plugins API source",
            ):
                validate_zara_source(Path(directory))


if __name__ == "__main__":
    unittest.main()
