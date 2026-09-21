"""Root-cancellation acceptance for the real JS/TS/Java/Kotlin expert chain."""

from __future__ import annotations

import tempfile
from pathlib import Path

from tests import test_js_ts_java_kotlin_inflight_recreation_e2e as base


CURRENT_DOTFILES_COMMIT = "fe8f7fa3c42803e0e505dcb6f7e4600d27649d9e"
ROOT_CANCEL_ZARA_CORE_COMMIT = "8177460982f94a5a60cf454c2fd4f9beae867a95"

# Reuse the canonical four-language runtime/chain and point it at the merged
# Core root-cancellation fix. This file owns no registry/runtime.
base.EXPECTED_DOTFILES_COMMIT = CURRENT_DOTFILES_COMMIT
base.EXPECTED_ZARA_CORE_COMMIT = ROOT_CANCEL_ZARA_CORE_COMMIT


class JsTsJavaKotlinRootCancellationE2ETests(
    base.JsTsJavaKotlinInflightRecreationE2ETests
):
    """Cancelling JavaScript must fence every live required descendant."""

    def test_root_cancellation_fences_entire_required_delegation_tree(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        backend = base._BlockAfterRealKotlinBackend()
        _host, published, handlers = self._runtime(
            state_root=Path(temporary.name) / "root-cancel-language-state",
            backend=backend,
        )
        registry = base.ExpertRegistry(engines=("swipl",))
        parent_handle, _child_handles = self._install_chain(
            registry,
            published,
            handlers,
        )
        outcome, worker = self._start_parent(registry, parent_handle)

        self.assertTrue(
            backend.completed.wait(timeout=5.0),
            "real Kotlin backend did not complete before root cancellation",
        )
        self.assertEqual(backend.kotlin_calls, 1)

        invocation_ids = registry.snapshot().invocation_ids
        self.assertEqual(len(invocation_ids), 4)
        root_invocation_id = next(
            invocation_id
            for invocation_id in invocation_ids
            if registry.explain(invocation_id)["expert_id"] == "zara:expert/javascript"
        )
        cancel_receipt = registry.cancel(root_invocation_id)
        self.assertIs(cancel_receipt["cancelled"], True)
        self.assertIs(cancel_receipt["committed"], False)

        backend.release.set()
        worker.join(timeout=5.0)

        self.assertFalse(worker.is_alive(), "root-cancelled language chain did not terminate")
        self.assertNotIn("error", outcome)
        result = outcome["result"]
        self.assertIs(result.verdict, base.ExpertVerdict.CANCELLED)
        self.assertEqual(result.data, {})
        self.assertEqual(result.evidence_refs, ())
        self.assertEqual(result.effect_receipts, ())
        self.assertIs(type(result.usage["model_calls"]), int)
        self.assertEqual(result.usage["model_calls"], 0)

        traces = [registry.explain(invocation_id) for invocation_id in invocation_ids]
        self.assertEqual(
            {trace["expert_id"] for trace in traces},
            set(base.EXPERT_IDS),
        )
        for trace in traces:
            self.assertEqual(
                trace["verdict"],
                "cancelled",
                f"late descendant committed after root cancellation: {trace!r}",
            )
            self.assertEqual(trace["evidence_refs"], [])
            self.assertEqual(trace.get("effect_receipts", []), [])
            self.assertIs(type(trace["usage"]["model_calls"]), int)
            self.assertEqual(trace["usage"]["model_calls"], 0)

        fresh_kotlin = self._activate(registry, "zara:expert/kotlin")
        fresh_result = registry.invoke(
            fresh_kotlin,
            "inspect",
            {
                "source": "object FreshAfterRootCancel { const val VALUE: Int = 43 }",
                "source_generation": "generation-kotlin-after-root-cancel",
            },
            limits=base.ExpertLimits(max_model_calls=0),
        )
        self.assertIs(fresh_result.verdict, base.ExpertVerdict.SUCCEEDED)
        self.assertTrue(fresh_result.evidence_refs)
        self.assertEqual(fresh_result.effect_receipts, ())
        self.assertIs(type(fresh_result.usage["model_calls"]), int)
        self.assertEqual(fresh_result.usage["model_calls"], 0)

    def test_exact_merged_root_cancellation_revision_is_pinned(self) -> None:
        self.assertEqual(base.EXPECTED_DOTFILES_COMMIT, CURRENT_DOTFILES_COMMIT)
        self.assertEqual(base.EXPECTED_ZARA_CORE_COMMIT, ROOT_CANCEL_ZARA_CORE_COMMIT)


if __name__ == "__main__":
    base.unittest.main()
