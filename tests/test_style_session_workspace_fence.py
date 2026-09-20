import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugins" / "zara-expert" / "lib"))

from zara_expert.composition import (
    CompositionError,
    InvocationFence,
    StyleOverlay,
    StyleScope,
    resolve_style,
)


class StyleSessionWorkspaceFenceTests(unittest.TestCase):
    def _fence(self, generation: int = 7) -> InvocationFence:
        return InvocationFence(
            workspace_id="dotfiles",
            workspace_generation=generation,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace, current: (
                workspace == "dotfiles" and current == generation
            ),
        )

    def test_session_overlay_requires_workspace_generation(self) -> None:
        with self.assertRaisesRegex(
            CompositionError,
            "session style overlay requires workspace generation",
        ):
            StyleOverlay(
                StyleScope.SESSION,
                {"indent": 8},
                "session:42",
                "s1",
            )

    def test_stale_session_overlay_never_crosses_workspace_generation(self) -> None:
        overlay = StyleOverlay(
            StyleScope.SESSION,
            {"indent": 8},
            "session:42",
            "s1",
            workspace_id="dotfiles",
            workspace_generation=6,
        )
        with self.assertRaisesRegex(
            CompositionError,
            "stale session style generation",
        ):
            resolve_style([overlay], language="nix", fence=self._fence())


if __name__ == "__main__":
    unittest.main()
