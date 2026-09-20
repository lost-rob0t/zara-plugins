"""Real Prolog/Python/Nim nested cancellation acceptance against exact Zara Core."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "fe8f7fa3c42803e0e505dcb6f7e4600d27649d9e"
EXPECTED_ZARA_CORE_COMMIT = "f7810b0cba602b1e00597d04dd419d30ac0ef949"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"

if ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertHost
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.language_source_contract import validate_language_source_contracts

if ZARA_CORE_ROOT:
    from zara.experts import ExpertDescriptor, ExpertLimits, ExpertRegistry, ExpertVerdict


def _run(*argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _checkout_head(root: Path, expected: str, label: str) -> None:
    result = _run("git", "rev-parse", "HEAD", cwd=root)
    if result.returncode != 0:
        raise AssertionError(f"cannot resolve {label} checkout: {result.stderr}")
    actual = result.stdout.strip()
    if actual != expected:
        raise AssertionError(
            f"{label} checkout must be exact: expected {expected}, got {actual}"
        )


class _BlockAfterRealNimBackend:
    """Hold one real Nim result after backend completion but before host commit."""

    def __init__(self) -> None:
        self._inner = SwiplBackend()
        self.completed = threading.Event()
        self.release = threading.Event()
        self.nim_calls = 0

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        result = self._inner.run(request)
        if request.get("namespace") != "nim-expert":
            return result
        self.nim_calls += 1
        self.completed.set()
        if not self.release.wait(timeout=5.0):
            raise AssertionError("test failed to release completed Nim backend result")
        return result


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class PrologPythonNimInflightCancellationE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for Zara Core expert E2E")
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT, "Dotfiles producer")
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "Zara Core")
        cls.sources = {
            language: [
                cls.dotfiles_root
                / ".zara"
                / "experts"
                / language
                / "kb"
                / "expert.pl"
            ]
            for language in ("prolog", "python", "nim")
        }
        for paths in cls.sources.values():
            for source in paths:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")

    def _runtime(self, *, state_root: Path, backend: Any):
        validate_language_source_contracts(self.sources)
        host = ExpertHost(backend, state_root=state_root)
        registered = register_language_family(host, self.sources)
        self.assertEqual(registered, frozenset({"prolog", "python", "nim"}))
        published = {item["expert_id"]: item for item in descriptors(registered)}
        handlers = {
            expert_id: make_language_expert_handler(host, expert_id)
            for expert_id in (
                "zara:expert/prolog",
                "zara:expert/python",
                "zara:expert/nim",
            )
        }
        return host, published, handlers

    @staticmethod
    def _activate(registry, expert_id: str):
        handle, receipt = registry.activate(
            "expert-builder-3",
            "workspace:prolog-python-nim-cancel",
            expert_id,
            expected_registry_generation=registry.generation,
            expected_runtime_generation=registry.runtime_generation,
        )
        if receipt["state"] != "active":
            raise AssertionError(f"failed to activate {expert_id}: {receipt!r}")
        return handle

    @staticmethod
    def _required_child_result(
        parent_result: dict[str, Any],
        child_result: Any,
    ) -> dict[str, Any]:
        """Required-child non-success must propagate without parent false-success."""

        if child_result.verdict is ExpertVerdict.SUCCEEDED:
            return parent_result
        return {
            "verdict": child_result.verdict.value,
            "data": {},
            "evidence_refs": list(child_result.evidence_refs),
            "usage": {"model_calls": child_result.usage.get("model_calls", 0)},
            "effect_receipts": list(child_result.effect_receipts),
        }

    def _install_chain(self, registry, published, handlers):
        child_handles: dict[str, Any] = {}
        prolog_handler = handlers["zara:expert/prolog"]
        python_handler = handlers["zara:expert/python"]
        nim_handler = handlers["zara:expert/nim"]

        def delegating_python(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            parent_result = python_handler(
                expert_operation=expert_operation,
                **payload,
            )
            child_result = registry.invoke(
                child_handles["zara:expert/nim"],
                "inspect",
                {
                    "source": "proc answer(): int = 42\n",
                    "source_generation": "generation-nim-inflight-cancel",
                },
                limits=ExpertLimits(max_model_calls=64),
            )
            return self._required_child_result(parent_result, child_result)

        def delegating_prolog(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            parent_result = prolog_handler(
                expert_operation=expert_operation,
                **payload,
            )
            child_result = registry.invoke(
                child_handles["zara:expert/python"],
                "inspect",
                {
                    "source": "def answer():\n    return 42\n",
                    "source_generation": "generation-python-inflight-cancel",
                },
                limits=ExpertLimits(max_model_calls=64),
            )
            return self._required_child_result(parent_result, child_result)

        registry.register(
            ExpertDescriptor.from_wire(published["zara:expert/prolog"]),
            delegating_prolog,
        )
        registry.register(
            ExpertDescriptor.from_wire(published["zara:expert/python"]),
            delegating_python,
        )
        registry.register(
            ExpertDescriptor.from_wire(published["zara:expert/nim"]),
            nim_handler,
        )
        parent_handle = self._activate(registry, "zara:expert/prolog")
        child_handles["zara:expert/python"] = self._activate(
            registry,
            "zara:expert/python",
        )
        child_handles["zara:expert/nim"] = self._activate(
            registry,
            "zara:expert/nim",
        )
        return parent_handle

    @staticmethod
    def _start_parent(registry, parent_handle):
        outcome: dict[str, Any] = {}

        def invoke() -> None:
            try:
                outcome["result"] = registry.invoke(
                    parent_handle,
                    "inspect",
                    {
                        "source": "fact(a).",
                        "source_generation": "generation-prolog-inflight-cancel",
                    },
                    limits=ExpertLimits(max_model_calls=0),
                )
            except BaseException as error:  # pragma: no cover - asserted by caller
                outcome["error"] = error

        worker = threading.Thread(target=invoke, daemon=True)
        worker.start()
        return outcome, worker

    def test_nested_real_nim_cancellation_propagates_before_commit(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        backend = _BlockAfterRealNimBackend()
        _host, published, handlers = self._runtime(
            state_root=Path(temporary.name) / "language-state",
            backend=backend,
        )
        registry = ExpertRegistry(engines=("swipl",))
        parent_handle = self._install_chain(registry, published, handlers)
        outcome, worker = self._start_parent(registry, parent_handle)

        self.assertTrue(
            backend.completed.wait(timeout=5.0),
            "real Nim backend did not complete before cancellation",
        )
        self.assertEqual(backend.nim_calls, 1)

        invocation_ids = registry.snapshot().invocation_ids
        self.assertEqual(len(invocation_ids), 3)
        nim_invocation_id = next(
            invocation_id
            for invocation_id in invocation_ids
            if registry.explain(invocation_id)["expert_id"] == "zara:expert/nim"
        )
        cancel_receipt = registry.cancel(nim_invocation_id)
        self.assertIs(cancel_receipt["cancelled"], True)
        self.assertIs(cancel_receipt["committed"], False)

        backend.release.set()
        worker.join(timeout=5.0)

        self.assertFalse(worker.is_alive(), "cancelled nested invocation did not terminate")
        self.assertNotIn("error", outcome)
        result = outcome["result"]
        self.assertIs(result.verdict, ExpertVerdict.CANCELLED)
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
            self.assertEqual(trace["verdict"], "cancelled")
            self.assertEqual(trace["evidence_refs"], [])
            self.assertEqual(trace.get("effect_receipts", []), [])
            self.assertIs(type(trace["usage"]["model_calls"]), int)
            self.assertEqual(trace["usage"]["model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
