import importlib.util
import unittest

from discord_test_support import install_zara_stubs

install_zara_stubs()

DISCORD_AVAILABLE = importlib.util.find_spec("discord") is not None
if DISCORD_AVAILABLE:
    from zara_discord_service.inspection import inspection_context


@unittest.skipUnless(DISCORD_AVAILABLE, "discord.py is provided by the Nix plugin environment")
class InspectionContextTests(unittest.TestCase):
    def test_metadata_only_context_marks_content_unavailable(self):
        context = inspection_context(
            display_name="Mina",
            content="",
            content_available=False,
        )

        self.assertIn("content_available=false", context)
        self.assertIn("Mina", context)
        self.assertNotIn("said:", context)

    def test_available_content_is_explicitly_marked_and_included(self):
        context = inspection_context(
            display_name="Mina",
            content="build failed",
            content_available=True,
        )

        self.assertIn("content_available=true", context)
        self.assertIn("build failed", context)


if __name__ == "__main__":
    unittest.main()
