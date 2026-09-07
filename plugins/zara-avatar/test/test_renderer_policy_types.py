from __future__ import annotations

import math
import unittest

import avatar_test_support

AVATAR = avatar_test_support.load_avatar_module()


class RendererPolicyTypeTests(unittest.TestCase):
    def test_rejects_scalar_or_empty_command_descriptors(self) -> None:
        for command in ("renderer", b"renderer", [], [""], ["renderer", ""]):
            with self.subTest(command=command):
                with self.assertRaises(ValueError):
                    AVATAR.RendererHost(command=command)  # type: ignore[arg-type]

    def test_rejects_malformed_lifecycle_timeouts(self) -> None:
        for key in ("startup_timeout", "request_timeout", "shutdown_grace"):
            for value in (True, False, 0, -1, "1", None, math.nan, math.inf, -math.inf):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        AVATAR.RendererHost(command=["renderer"], **{key: value})

    def test_rejects_malformed_request_timeout_before_process_use(self) -> None:
        host = AVATAR.RendererHost(command=["renderer"])
        for timeout in (True, False, 0, -1, "1", math.nan, math.inf, -math.inf):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    host.request("LoadAvatar", {}, timeout=timeout)

    def test_accepts_finite_positive_timeout_policy(self) -> None:
        host = AVATAR.RendererHost(
            command=["renderer"],
            startup_timeout=0.25,
            request_timeout=0.5,
            shutdown_grace=0.75,
        )
        self.assertEqual(["renderer"], host.command)
        self.assertEqual(0.25, host.startup_timeout)
        self.assertEqual(0.5, host.request_timeout)
        self.assertEqual(0.75, host.shutdown_grace)


if __name__ == "__main__":
    unittest.main()
