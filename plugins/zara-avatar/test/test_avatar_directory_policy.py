from __future__ import annotations

import unittest

import avatar_test_support

AVATAR = avatar_test_support.load_avatar_module()


class AvatarDirectoryPolicyTests(unittest.TestCase):
    def test_rejects_non_string_avatar_directory(self) -> None:
        for value in (None, True, False, 0, 1, b"/tmp/avatars", [], {}):
            with self.subTest(value=value):
                plugin = AVATAR.ZaraAvatarPlugin()
                with self.assertRaises(ValueError):
                    plugin._configure({"avatar_directory": value})

    def test_accepts_non_empty_string_avatar_directory(self) -> None:
        plugin = AVATAR.ZaraAvatarPlugin()
        plugin._configure({"avatar_directory": "~/zara-avatar-test"})
        self.assertEqual("~/zara-avatar-test", plugin._avatar_directory)


if __name__ == "__main__":
    unittest.main()
