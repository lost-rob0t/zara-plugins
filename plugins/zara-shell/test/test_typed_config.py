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


class TypedShellConfigurationTest(unittest.TestCase):
    def test_allowed_programs_reject_non_string_entries(self) -> None:
        with self.assertRaisesRegex(ShellError, "allowed_programs must contain strings"):
            ZaraShellPlugin._string_list(["printf", 7], "allowed_programs")

    def test_allowed_roots_reject_non_string_entries(self) -> None:
        with self.assertRaisesRegex(ShellError, "allowed_roots must contain strings"):
            ZaraShellPlugin._string_list(["/tmp", False], "allowed_roots")


if __name__ == "__main__":
    unittest.main()
