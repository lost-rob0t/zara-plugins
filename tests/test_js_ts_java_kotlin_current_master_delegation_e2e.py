"""Exact-current producer acceptance for JS/TS + Java/Kotlin delegation."""

from __future__ import annotations

from tests import test_js_ts_java_kotlin_current_core_delegation_e2e as base


CURRENT_DOTFILES_COMMIT = "fe8f7fa3c42803e0e505dcb6f7e4600d27649d9e"
CURRENT_ZARA_CORE_COMMIT = "0561fdbeadde3c2d7ed4ac94c5427f0c10421dac"

# Reuse the canonical lane test instead of creating a second expert/registry path.
# Only the exact producer revisions change here.
base.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES_COMMIT
base.EXPECTED_ZARA_CORE_COMMIT = CURRENT_ZARA_CORE_COMMIT


class JsTsJavaKotlinCurrentMasterDelegationE2ETests(
    base.JsTsJavaKotlinCurrentCoreDelegationE2ETests
):
    """Run the existing four-language contract against exact current producers."""

    def test_exact_current_producer_revisions_are_pinned(self) -> None:
        self.assertEqual(base.EXPECTED_DOTFILES_COMMIT, CURRENT_DOTFILES_COMMIT)
        self.assertEqual(base.EXPECTED_ZARA_CORE_COMMIT, CURRENT_ZARA_CORE_COMMIT)


if __name__ == "__main__":
    base.unittest.main()
