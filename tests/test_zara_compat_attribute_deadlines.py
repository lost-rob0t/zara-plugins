from __future__ import annotations

import time
import unittest

from scripts.zara_compat import (
    require_metadata,
    require_service_activation_contract,
    require_tool_names,
)


class BlockingAttribute:
    def __get__(self, instance, owner):
        time.sleep(1.0)
        return "late"


class BlockingMetadata:
    name = BlockingAttribute()


class BlockingActivation:
    enabled_by_default = BlockingAttribute()


class BlockingTool:
    name = BlockingAttribute()


class ZaraCompatibilityAttributeDeadlineTest(unittest.TestCase):
    def test_metadata_attribute_read_is_bounded(self) -> None:
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            require_metadata(
                {
                    "name": "zara-example",
                    "version": "1.0.0",
                    "api_version": "1",
                    "plugin_type": "service",
                    "description": "example",
                },
                BlockingMetadata(),
                timeout=0.05,
            )
        self.assertLess(time.monotonic() - started, 0.5)

    def test_activation_attribute_read_is_bounded(self) -> None:
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            require_service_activation_contract(
                "zara-example",
                BlockingActivation(),
                timeout=0.05,
            )
        self.assertLess(time.monotonic() - started, 0.5)

    def test_tool_name_attribute_read_is_bounded(self) -> None:
        started = time.monotonic()
        with self.assertRaises(TimeoutError):
            require_tool_names(
                "zara-example",
                [BlockingTool()],
                {},
                timeout=0.05,
            )
        self.assertLess(time.monotonic() - started, 0.5)


if __name__ == "__main__":
    unittest.main()
