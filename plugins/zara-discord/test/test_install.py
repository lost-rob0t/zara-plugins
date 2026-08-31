import importlib.util
import tempfile
import unittest
from pathlib import Path

from discord_test_support import LIB_ROOT
from zara_discord_service.install import install


def package_available(name):
    specification = importlib.util.find_spec(name)
    return specification is not None and specification.submodule_search_locations is not None


DEPENDENCIES_AVAILABLE = package_available("discord") and package_available("audioop")


@unittest.skipUnless(
    DEPENDENCIES_AVAILABLE,
    "discord.py and audioop-lts are provided by the Nix plugin environment",
)
class InstallerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.home = root / "home"
        self.xdg = root / "xdg"

    def tearDown(self):
        self.temporary.cleanup()

    def test_places_entry_code_dependencies_and_config_in_separate_namespaces(self):
        result = install(home=self.home, xdg_config_home=self.xdg)

        self.assertEqual(
            result.plugin_entry,
            self.home / ".zarathushtra" / "plugins" / "zara_discord.py",
        )
        self.assertTrue(result.plugin_entry.is_file())
        self.assertEqual(
            result.config_dir,
            self.xdg / "zarathushtra" / "plugins" / "zara-discord",
        )
        self.assertTrue(
            result.config_dir.joinpath("lib", "zara_discord_service", "plugin.py").is_file()
        )
        self.assertTrue(result.config_dir.joinpath("lib", "discord", "__init__.py").is_file())
        self.assertTrue(result.config_dir.joinpath("lib", "audioop").is_dir())
        self.assertIn(
            "ZARA_DISCORD_TOKEN",
            result.config_dir.joinpath("README.txt").read_text(),
        )

    def test_preserves_existing_settings_and_token(self):
        config_dir = self.xdg / "zarathushtra" / "plugins" / "zara-discord"
        config_dir.mkdir(parents=True)
        config_dir.joinpath("settings.json").write_text('{"version": 1, "guilds": {}}\n')
        config_dir.joinpath("token").write_text("keep-me\n")

        install(home=self.home, xdg_config_home=self.xdg)

        self.assertEqual(
            config_dir.joinpath("settings.json").read_text(),
            '{"version": 1, "guilds": {}}\n',
        )
        self.assertEqual(config_dir.joinpath("token").read_text(), "keep-me\n")


if __name__ == "__main__":
    unittest.main()
