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
                [SimpleNamespace(name="   ")],
                {},
            )

    def test_tool_name_must_be_canonical_without_edge_whitespace(self) -> None:
        with self.assertRaisesRegex(
            CompatibilityError,
            "zara-example.*surrounding whitespace",
        ):
            require_tool_names(
                "zara-example",
                [SimpleNamespace(name=" coding.status ")],
                {},
            )


if __name__ == "__main__":
    unittest.main()
