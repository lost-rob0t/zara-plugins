import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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

    @property
    def config_dir(self):
        return self.xdg / "zarathushtra" / "plugins" / "zara-discord"

    @property
    def plugin_entry(self):
        return self.home / ".zarathushtra" / "plugins" / "zara_discord.py"

    def seed_existing_install(self):
        library_dir = self.config_dir / "lib"
        library_dir.mkdir(parents=True)
        library_dir.joinpath("old-marker.txt").write_text("old-library\n")
        self.plugin_entry.parent.mkdir(parents=True)
        self.plugin_entry.write_text("old-wrapper\n")
        self.config_dir.joinpath("settings.json").write_text('{"version": 1, "guilds": {}}\n')
        self.config_dir.joinpath("token").write_text("keep-me\n")

    def assert_existing_install_intact(self):
        self.assertEqual(
            self.config_dir.joinpath("lib", "old-marker.txt").read_text(),
            "old-library\n",
        )
        self.assertEqual(self.plugin_entry.read_text(), "old-wrapper\n")
        self.assertEqual(
            self.config_dir.joinpath("settings.json").read_text(),
            '{"version": 1, "guilds": {}}\n',
        )
        self.assertEqual(self.config_dir.joinpath("token").read_text(), "keep-me\n")
        self.assertFalse(self.config_dir.joinpath(".lib.tmp").exists())
        self.assertFalse(self.config_dir.joinpath(".lib.backup").exists())
        self.assertFalse(self.plugin_entry.with_name(".zara_discord.py.tmp").exists())
        self.assertFalse(self.plugin_entry.with_name(".zara_discord.py.backup").exists())

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
        self.config_dir.mkdir(parents=True)
        self.config_dir.joinpath("settings.json").write_text('{"version": 1, "guilds": {}}\n')
        self.config_dir.joinpath("token").write_text("keep-me\n")

        install(home=self.home, xdg_config_home=self.xdg)

        self.assertEqual(
            self.config_dir.joinpath("settings.json").read_text(),
            '{"version": 1, "guilds": {}}\n',
        )
        self.assertEqual(self.config_dir.joinpath("token").read_text(), "keep-me\n")

    def test_failed_library_publication_rolls_back_existing_install(self):
        self.seed_existing_install()
        real_replace = os.replace
        library_dir = self.config_dir / "lib"

        def fail_library_publication(source, destination):
            if Path(destination) == library_dir and Path(source).name == ".lib.tmp":
                raise OSError("injected library publication failure")
            return real_replace(source, destination)

        with mock.patch("zara_discord_service.install.os.replace", side_effect=fail_library_publication):
            with self.assertRaisesRegex(OSError, "library publication failure"):
                install(home=self.home, xdg_config_home=self.xdg)

        self.assert_existing_install_intact()

    def test_failed_wrapper_publication_rolls_back_existing_install(self):
        self.seed_existing_install()
        real_replace = os.replace

        def fail_wrapper_publication(source, destination):
            if Path(destination) == self.plugin_entry and Path(source).name == ".zara_discord.py.tmp":
                raise OSError("injected wrapper publication failure")
            return real_replace(source, destination)

        with mock.patch("zara_discord_service.install.os.replace", side_effect=fail_wrapper_publication):
            with self.assertRaisesRegex(OSError, "wrapper publication failure"):
                install(home=self.home, xdg_config_home=self.xdg)

        self.assert_existing_install_intact()


if __name__ == "__main__":
    unittest.main()
