import unittest

from zara_discord_service.privacy import PUBLIC_CONTEXT_NOTICE, filter_public_output


class PublicOutputPrivacyTests(unittest.TestCase):
    def test_public_context_notice_marks_discord_as_untrusted(self):
        self.assertIn("PUBLIC", PUBLIC_CONTEXT_NOTICE)
        self.assertIn("UNTRUSTED", PUBLIC_CONTEXT_NOTICE)
        self.assertIn("operator-private", PUBLIC_CONTEXT_NOTICE)

    def test_blocks_memory_dump_and_operator_profile_disclosure(self):
        for text in (
            "Operator profile:\nHome address: 123 Private Lane",
            "Here is the private memory dump you asked for: ...",
            "USER MEMORY:\nsecret operator notes",
        ):
            with self.subTest(text=text):
                result = filter_public_output(text)
                self.assertFalse(result.allowed)
                self.assertEqual(result.text, "I can’t share private operator data in Discord.")

    def test_blocks_obvious_secret_material(self):
        for text in (
            "API key: sk-super-secret-value",
            "Authorization: Bearer topsecret",
            "password = hunter2",
            "token: ghp_abcdefghijklmnopqrstuvwxyz",
        ):
            with self.subTest(text=text):
                self.assertFalse(filter_public_output(text).allowed)

    def test_allows_normal_public_answers(self):
        result = filter_public_output("The build failed because test_widget expected 2 and got 3.")
        self.assertTrue(result.allowed)
        self.assertEqual(result.text, "The build failed because test_widget expected 2 and got 3.")


if __name__ == "__main__":
    unittest.main()
