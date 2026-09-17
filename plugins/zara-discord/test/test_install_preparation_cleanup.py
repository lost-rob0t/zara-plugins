import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from discord_test_support import LIB_ROOT
from zara_discord_service.install import install


class InstallerPreparationCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.home = self.root / "home"
        self.xdg = self.root / "xdg"
        self.config_dir = self.xdg / "zarathushtra" / "plugins" / "zara-discord"
        self.plugin_entry = self.home / ".zarathushtra" / "plugins" / "zara_discord.py"

        library_dir = self.config_dir / "lib"
        library_dir.mkdir(parents=True)
        library_dir.joinpath("old-marker.txt").write_text("old-library\n", encoding="utf-8")
        self.plugin_entry.parent.mkdir(parents=True)
        self.plugin_entry.write_text("old-wrapper\n", encoding="utf-8")
        self.config_dir.joinpath("settings.json").write_text(
            '{"version": 1, "guilds": {}}\n', encoding="utf-8"
        )
        self.config_dir.joinpath("token").write_text("keep-me\n", encoding="utf-8")

        self.fake_discord = self.root / "fake-discord"
        self.fake_discord.mkdir()
        self.fake_discord.joinpath("__init__.py").write_text("", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def test_missing_dependency_cleans_staging_without_mutating_existing_install(self):
        def find_spec(name):
            if name == "discord":
                return SimpleNamespace(submodule_search_locations=[str(self.fake_discord)])
            if name == "audioop":
                return None
            raise AssertionError(f"unexpected dependency lookup: {name}")

        with mock.patch(
            "zara_discord_service.install.importlib.util.find_spec",
            side_effect=find_spec,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "audioop compatibility package is not installed",
            ):
                install(home=self.home, xdg_config_home=self.xdg)

        self.assertEqual(
            self.config_dir.joinpath("lib", "old-marker.txt").read_text(encoding="utf-8"),
            "old-library\n",
        )
        self.assertEqual(self.plugin_entry.read_text(encoding="utf-8"), "old-wrapper\n")
        self.assertEqual(
            self.config_dir.joinpath("settings.json").read_text(encoding="utf-8"),
            '{"version": 1, "guilds": {}}\n',
        )
        self.assertEqual(
            self.config_dir.joinpath("token").read_text(encoding="utf-8"),
            "keep-me\n",
        )
        self.assertFalse(self.config_dir.joinpath(".lib.tmp").exists())
        self.assertFalse(self.plugin_entry.with_name(".zara_discord.py.tmp").exists())
        self.assertFalse(self.config_dir.joinpath(".lib.backup").exists())
        self.assertFalse(self.plugin_entry.with_name(".zara_discord.py.backup").exists())
        self.assertFalse(self.config_dir.joinpath(".install-transaction.json").exists())


if __name__ == "__main__":
    unittest.main()
