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
EXPECTED_ZARA_CORE_COMMIT = "3909dd259e7ce689fcd3e4f132cd5e0045387b78"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"
LANGUAGES = ("javascript", "typescript", "java", "kotlin")
EXPERT_IDS = tuple(f"zara:expert/{language}" for language in LANGUAGES)
NAMESPACES = frozenset(f"{language}-expert" for language in LANGUAGES)

if ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertHost
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.language_source_contract import validate_language_source_contracts

if ZARA_CORE_ROOT:
    from zara.experts import (
        ExpertDescriptor,
        ExpertLimits,
        ExpertRegistry,
        ExpertStaleGenerationError,
        ExpertVerdict,
    )


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


class _BlockAfterRealKotlinBackend:
    """Hold one real Kotlin result between backend completion and host/Core commit."""

    def __init__(self) -> None:
        self._inner = SwiplBackend()
        self.completed = threading.Event()
        self.release = threading.Event()
        self.kotlin_calls = 0

    def run(self, request: dict[str, Any]) -> dict[str, Any]:
        result = self._inner.run(request)
        if request.get("namespace") != "kotlin-expert":
            return result
        self.kotlin_calls += 1
        self.completed.set()
        if not self.release.wait(timeout=5.0):
            raise AssertionError("test failed to release completed Kotlin backend result")
        return result


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class JsTsJavaKotlinInflightRecreationE2ETests(unittest.TestCase):
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
            for language in LANGUAGES
        }
        for paths in cls.sources.values():
            for source in paths:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")

    @staticmethod
    def _payloads() -> dict[str, dict[str, str]]:
        return {
            "zara:expert/javascript": {
                "source": "export const answer = 42;",
                "source_generation": "generation-javascript-inflight-restart",
            },
            "zara:expert/typescript": {
                "source": "export const answer: number = 42;",
                "source_generation": "generation-typescript-inflight-restart",
            },
            "zara:expert/java": {
                "source": "public final class Answer { static final int VALUE = 42; }",
                "source_generation": "generation-java-inflight-restart",
            },
            "zara:expert/kotlin": {
                "source": "object Answer { const val VALUE: Int = 42 }",
                "source_generation": "generation-kotlin-inflight-restart",
            },
        }

    def _runtime(
        self,
        *,
        state_root: Path,
        backend: Any | None = None,
    ):
        validate_language_source_contracts(self.sources)
        host = ExpertHost(
            backend if backend is not None else SwiplBackend(),
            state_root=state_root,
        )
        registered = register_language_family(host, self.sources)
        self.assertEqual(registered, frozenset(LANGUAGES))
        catalog = {item["expert_id"]: item for item in descriptors(registered)}
        published = {expert_id: catalog[expert_id] for expert_id in EXPERT_IDS}
        self.assertEqual(set(published), set(EXPERT_IDS))
        for item in published.values():
            self.assertEqual(item["availability"], "available")
        for expert_id, item in catalog.items():
            if expert_id not in EXPERT_IDS:
                self.assertEqual(item["availability"], "absent")
        handlers = {
            expert_id: make_language_expert_handler(host, expert_id)
            for expert_id in EXPERT_IDS
        }
        return host, published, handlers

    @staticmethod
    def _activate(registry, expert_id: str):
        handle, receipt = registry.activate(
            "expert-builder-4",
            "workspace:js-ts-java-kotlin-inflight",
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
        """Required delegated children fail the whole symbolic chain closed."""

        if child_result.verdict is ExpertVerdict.SUCCEEDED:
            return parent_result
        return {
            "verdict": child_result.verdict.value,
            "data": {},
            "evidence_refs": list(child_result.evidence_refs),
            "usage": {"model_calls": child_result.usage.get("model_calls", 0)},
            "effect_receipts": [],
        }

    def _install_chain(self, registry, published, handlers):
        payloads = self._payloads()
        child_handles: dict[str, Any] = {}

        javascript_handler = handlers["zara:expert/javascript"]
        typescript_handler = handlers["zara:expert/typescript"]
        java_handler = handlers["zara:expert/java"]
        kotlin_handler = handlers["zara:expert/kotlin"]

        def delegating_java(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            parent_result = java_handler(
                expert_operation=expert_operation,
                **payload,
            )
            child_result = registry.invoke(
                child_handles["zara:expert/kotlin"],
                "inspect",
                payloads["zara:expert/kotlin"],
                limits=ExpertLimits(max_model_calls=64),
            )
            return self._required_child_result(parent_result, child_result)

        def delegating_typescript(
            *,
            expert_operation: str,
            **payload: Any,
        ) -> dict[str, Any]:
            parent_result = typescript_handler(
                expert_operation=expert_operation,
                **payload,
            )
            child_result = registry.invoke(
                child_handles["zara:expert/java"],
                "inspect",
                payloads["zara:expert/java"],
                limits=ExpertLimits(max_model_calls=64),
            )
            return self._required_child_result(parent_result, child_result)

        def delegating_javascript(
            *,
            expert_operation: str,
            **payload: Any,
        ) -> dict[str, Any]:
            parent_result = javascript_handler(
                expert_operation=expert_operation,
                **payload,
            )
            child_result = registry.invoke(
                child_handles["zara:expert/typescript"],
                "inspect",
                payloads["zara:expert/typescript"],
                limits=ExpertLimits(max_model_calls=64),
            )
            return self._required_child_result(parent_result, child_result)

        registry.register(
            ExpertDescriptor.from_wire(published["zara:expert/javascript"]),
            delegating_javascript,
        )
        registry.register(
            ExpertDescriptor.from_wire(published["zara:expert/typescript"]),
            delegating_typescript,
        )
        registry.register(
            ExpertDescriptor.from_wire(published["zara:expert/java"]),
            delegating_java,
        )
        registry.register(
            ExpertDescriptor.from_wire(published["zara:expert/kotlin"]),
            kotlin_handler,
        )

        parent_handle = self._activate(registry, "zara:expert/javascript")
        for expert_id in EXPERT_IDS[1:]:
            child_handles[expert_id] = self._activate(registry, expert_id)
        return parent_handle, child_handles

    def _start_parent(self, registry, parent_handle):
        outcome: dict[str, Any] = {}
        payload = self._payloads()["zara:expert/javascript"]

        def invoke() -> None:
            try:
                outcome["result"] = registry.invoke(
                    parent_handle,
                    "inspect",
                    payload,
                    limits=ExpertLimits(max_model_calls=0),
                )
            except BaseException as error:  # pragma: no cover - asserted by caller
                outcome["error"] = error

        worker = threading.Thread(target=invoke, daemon=True)
        worker.start()
        return outcome, worker

    def test_nested_real_kotlin_completion_is_fenced_by_core_reload(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        state_root = Path(temporary.name) / "core-reload-language-state"
        backend = _BlockAfterRealKotlinBackend()
        host, published, handlers = self._runtime(
            state_root=state_root,
            backend=backend,
        )
        registry = ExpertRegistry(engines=("swipl",))
        parent_handle, _child_handles = self._install_chain(
            registry,
            published,
            handlers,
        )
        outcome, worker = self._start_parent(registry, parent_handle)
        self.assertTrue(
            backend.completed.wait(timeout=5.0),
            "real Kotlin backend did not complete before the Core reload fence",
        )
        self.assertEqual(backend.kotlin_calls, 1)
        self.assertEqual(len(registry.snapshot().invocation_ids), 4)

        prior_generation = registry.generation
        registry.reload(
            (
                (
                    ExpertDescriptor.from_wire(published[expert_id]),
                    make_language_expert_handler(host, expert_id),
                )
                for expert_id in EXPERT_IDS
            )
        )
        self.assertGreater(registry.generation, prior_generation)
        backend.release.set()
        worker.join(timeout=5.0)

        self.assertFalse(worker.is_alive(), "late nested invocation did not terminate")
        self.assertNotIn("result", outcome)
        self.assertIsInstance(outcome.get("error"), ExpertStaleGenerationError)

        fresh_handle = self._activate(registry, "zara:expert/kotlin")
        fresh = registry.invoke(
            fresh_handle,
            "inspect",
            {
                "source": "object FreshAfterReload { const val VALUE: Int = 43 }",
                "source_generation": "generation-kotlin-after-core-reload",
            },
            limits=ExpertLimits(max_model_calls=0),
        )
        self.assertIs(fresh.verdict, ExpertVerdict.SUCCEEDED)
        self.assertIs(type(fresh.usage["model_calls"]), int)
        self.assertEqual(fresh.usage["model_calls"], 0)
        self.assertEqual(fresh.effect_receipts, ())
        self.assertTrue(fresh.evidence_refs)

    def test_nested_real_kotlin_completion_is_fenced_by_host_recreation(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        state_root = Path(temporary.name) / "host-recreation-language-state"
        backend = _BlockAfterRealKotlinBackend()
        first_host, published, first_handlers = self._runtime(
            state_root=state_root,
            backend=backend,
        )
        self.assertTrue(
            first_host.assert_fact(
                "kotlin-expert",
                "remembered(inflight_restart)",
                persistent=True,
            )
        )
        first_registry = ExpertRegistry(engines=("swipl",))
        parent_handle, child_handles = self._install_chain(
            first_registry,
            published,
            first_handlers,
        )
        outcome, worker = self._start_parent(first_registry, parent_handle)
        self.assertTrue(
            backend.completed.wait(timeout=5.0),
            "real Kotlin backend did not complete before host recreation",
        )
        self.assertEqual(backend.kotlin_calls, 1)

        revoked = first_host.clear_registrations()
        self.assertEqual(frozenset(revoked), NAMESPACES)

        second_host, republished, second_handlers = self._runtime(
            state_root=state_root,
        )
        second_registry = ExpertRegistry(engines=("swipl",))
        for expert_id in EXPERT_IDS:
            second_registry.register(
                ExpertDescriptor.from_wire(republished[expert_id]),
                second_handlers[expert_id],
            )

        backend.release.set()
        worker.join(timeout=5.0)
        self.assertFalse(worker.is_alive(), "revoked nested invocation did not terminate")
        self.assertNotIn("error", outcome)
        failed = outcome["result"]
        self.assertIs(failed.verdict, ExpertVerdict.UNKNOWN)
        self.assertEqual(failed.data, {})
        self.assertEqual(failed.evidence_refs, ())
        self.assertIs(type(failed.usage["model_calls"]), int)
        self.assertEqual(failed.usage["model_calls"], 0)
        self.assertEqual(failed.effect_receipts, ())

        stale = first_registry.invoke(
            child_handles["zara:expert/kotlin"],
            "inspect",
            {
                "source": "object StaleProcess { const val VALUE: Int = 45 }",
                "source_generation": "generation-kotlin-stale-process",
            },
            limits=ExpertLimits(max_model_calls=0),
        )
        self.assertIs(stale.verdict, ExpertVerdict.UNKNOWN)
        self.assertEqual(stale.evidence_refs, ())
        self.assertIs(type(stale.usage["model_calls"]), int)
        self.assertEqual(stale.usage["model_calls"], 0)
        self.assertEqual(stale.effect_receipts, ())

        _session_path, persistent_path = second_host.state_files("kotlin-expert")
        self.assertIn(
            "remembered(inflight_restart).",
            persistent_path.read_text(encoding="utf-8"),
        )

        fresh_handle = self._activate(second_registry, "zara:expert/kotlin")
        fresh = second_registry.invoke(
            fresh_handle,
            "inspect",
            {
                "source": "object FreshAfterRestart { const val VALUE: Int = 44 }",
                "source_generation": "generation-kotlin-after-host-recreation",
            },
            limits=ExpertLimits(max_model_calls=0),
        )
        self.assertIs(fresh.verdict, ExpertVerdict.SUCCEEDED)
        self.assertIs(type(fresh.usage["model_calls"]), int)
        self.assertEqual(fresh.usage["model_calls"], 0)
        self.assertEqual(fresh.effect_receipts, ())
        self.assertTrue(fresh.evidence_refs)


if __name__ == "__main__":
    unittest.main()
