from __future__ import annotations

import unittest
from types import SimpleNamespace

from scripts.zara_compat import CompatibilityError, require_tool_names


class ZaraCompatibilityToolMetadataTest(unittest.TestCase):
    def test_tool_name_must_not_be_blank_whitespace(self) -> None:
        with self.assertRaisesRegex(
            CompatibilityError,
            "zara-example.*empty name",
        ):
            require_tool_names(
                "zara-example",
                [SimpleNamespace(name="   ", description="Useful tool")],
                {},
            )

    def test_tool_description_must_not_be_blank(self) -> None:
        with self.assertRaisesRegex(
            CompatibilityError,
            "zara-example.*example.read.*empty description",
        ):
            require_tool_names(
                "zara-example",
                [SimpleNamespace(name="example.read", description="   ")],
                {},
            )


if __name__ == "__main__":
    unittest.main()
