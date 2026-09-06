import sys
import types
import unittest
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))


@dataclass(frozen=True)
class PluginMetadata:
    name: str
    version: str = ""
    api_version: str = "1"
    description: str = ""


class ServicePlugin:
    pass


zara = types.ModuleType("zara")
zara_plugins = types.ModuleType("zara.plugins")
zara_plugins.PluginMetadata = PluginMetadata
zara_plugins.ServicePlugin = ServicePlugin
sys.modules.setdefault("zara", zara)
sys.modules.setdefault("zara.plugins", zara_plugins)

from zara_shell.domain import ShellError
from zara_shell.plugin import ZaraShellPlugin


class Runtime:
    def __init__(self, shell_config):
        self.configuration = {"plugins": {"zara-shell": shell_config}}


class TypedShellConfigurationTest(unittest.TestCase):
    def test_allowed_programs_reject_non_string_entries(self) -> None:
        with self.assertRaisesRegex(ShellError, "allowed_programs must contain strings"):
            ZaraShellPlugin._string_list(["printf", 7], "allowed_programs")

    def test_allowed_roots_reject_non_string_entries(self) -> None:
        with self.assertRaisesRegex(ShellError, "allowed_roots must contain strings"):
            ZaraShellPlugin._string_list(["/tmp", False], "allowed_roots")

    def test_byte_limits_are_not_coerced(self) -> None:
        for field, value in (
            ("max_output_bytes", True),
            ("max_input_bytes", 1.5),
            ("max_environment_bytes", "64"),
        ):
            config = {
                "allowed_programs": ["printf"],
                "allowed_roots": ["/tmp"],
                field: value,
            }
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(ShellError, f"{field} must be a positive integer"):
                    ZaraShellPlugin().start(Runtime(config))

    def test_runtime_deadline_is_not_coerced(self) -> None:
        for value in (True, "1.0"):
            config = {
                "allowed_programs": ["printf"],
                "allowed_roots": ["/tmp"],
                "max_runtime_seconds": value,
            }
            with self.subTest(value=value):
                with self.assertRaisesRegex(ShellError, "max_runtime_seconds must be finite positive"):
                    ZaraShellPlugin().start(Runtime(config))


if __name__ == "__main__":
    unittest.main()
