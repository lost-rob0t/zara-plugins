from __future__ import annotations

import unittest

from scripts.zara_compat_runtime import CompatibilityRuntime


class CompatibilityRuntimeSymbolTests(unittest.TestCase):
    def test_register_symbol_tracks_full_runtime_shape(self) -> None:
        runtime = CompatibilityRuntime("zara-expert")

        registration_id = runtime.register_symbol(
            "zara:expert/lisp",
            "expert",
            {"resource_limits": {"max_model_calls": 0}},
            priority=7,
            docs="Pure-symbolic Lisp expert",
            capabilities=("expert.invoke",),
            source="dotfiles:.zara/experts/lisp",
        )

        self.assertEqual(registration_id, 1)
        self.assertEqual(
            runtime.symbols,
            [
                {
                    "registration_id": 1,
                    "symbol": "zara:expert/lisp",
                    "kind": "expert",
                    "value": {"resource_limits": {"max_model_calls": 0}},
                    "priority": 7,
                    "docs": "Pure-symbolic Lisp expert",
                    "capabilities": ("expert.invoke",),
                    "source": "dotfiles:.zara/experts/lisp",
                }
            ],
        )

    def test_shutdown_fences_late_symbol_registration(self) -> None:
        runtime = CompatibilityRuntime("zara-expert")
        runtime.register_symbol("zara:expert/lisp", "expert", {})
        runtime._shutdown()

        self.assertEqual(runtime.symbols, [])
        with self.assertRaisesRegex(RuntimeError, "closed"):
            runtime.register_symbol("zara:expert/common-lisp", "expert", {})


if __name__ == "__main__":
    unittest.main()
