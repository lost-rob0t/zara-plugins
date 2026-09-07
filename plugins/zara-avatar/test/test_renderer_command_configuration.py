from __future__ import annotations

import unittest

import avatar_test_support

AVATAR = avatar_test_support.load_avatar_module()


class RendererCommandConfigurationTests(unittest.TestCase):
    def test_rejects_empty_explicit_renderer_command_elements(self) -> None:
        for command in ([""], ["renderer", ""], ["", "main.mjs"]):
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    AVATAR._resolve_renderer_command({"renderer_command": command})

    def test_accepts_non_empty_explicit_renderer_command(self) -> None:
        command = ["renderer", "main.mjs"]
        self.assertEqual(
            command,
            AVATAR._resolve_renderer_command({"renderer_command": command}),
        )


if __name__ == "__main__":
    unittest.main()
