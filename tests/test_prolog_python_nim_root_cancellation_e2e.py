"""Root-cancellation acceptance for the real Prolog/Python/Nim expert chain."""

from __future__ import annotations

import tempfile
from pathlib import Path

from tests import test_prolog_python_nim_inflight_cancellation_e2e as base


EXPECTED_ZARA_CORE_COMMIT = "8177460982f94a5a60cf454c2fd4f9beae867a95"
base.EXPECTED_ZARA_CORE_COMMIT = EXPECTED_ZARA_CORE_COMMIT


class PrologPythonNimRootCancellationE2ETests(
    base.PrologPythonNimInflightCancellationE2ETests
):
    """A cancelled root must fence every still-live required descendant."""

    def test_root_cancellation_fences_entire_required_delegation_tree(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        backend = base._BlockAfterRealNimBackend()
        _host, published, handlers = self._runtime(
            state_root=Path(temporary.name) / "language-state",
            backend=backend,
        )
        registry = base.ExpertRegistry(engines=("swipl",))
        parent_handle = self._install_chain(registry, published, handlers)
        outcome, worker = self._start_parent(registry, parent_handle)

        self.assertTrue(
            backend.completed.wait(timeout=5.0),
            "real Nim backend did not complete before root cancellation",
        )
        self.assertEqual(backend.nim_calls, 1)

        invocation_ids = registry.snapshot().invocation_ids
        self.assertEqual(len(invocation_ids), 3)
        root_invocation_id = next(
            invocation_id
            for invocation_id in invocation_ids
            if registry.explain(invocation_id)["expert_id"] == "zara:expert/prolog"
        )
        cancel_receipt = registry.cancel(root_invocation_id)
        self.assertIs(cancel_receipt["cancelled"], True)
        self.assertIs(cancel_receipt["committed"], False)

        backend.release.set()
        worker.join(timeout=5.0)

        self.assertFalse(worker.is_alive(), "root-cancelled delegation tree did not terminate")
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
            {
                "zara:expert/prolog",
                "zara:expert/python",
                "zara:expert/nim",
            },
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

        fresh_parent = self._activate(registry, "zara:expert/prolog")
        fresh_result = registry.invoke(
            fresh_parent,
            "inspect",
            {
                "source": "fact(fresh_turn).",
                "source_generation": "generation-prolog-after-root-cancel",
            },
            limits=base.ExpertLimits(max_model_calls=0),
        )
        self.assertIs(fresh_result.verdict, base.ExpertVerdict.SUCCEEDED)
        self.assertTrue(fresh_result.evidence_refs)
        self.assertEqual(fresh_result.effect_receipts, ())
        self.assertIs(type(fresh_result.usage["model_calls"]), int)
        self.assertEqual(fresh_result.usage["model_calls"], 0)


if __name__ == "__main__":
    base.unittest.main()
