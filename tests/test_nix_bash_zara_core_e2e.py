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
EXPECTED_DOTFILES_COMMIT = "1b93e01f3482e49a853f651eb28c21eb1d9cad0e"
EXPECTED_ZARA_CORE_COMMIT = "b6eafa866f9c24533bc1c8dec27c3c17e3acebcc"
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


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CORE_ROOT,
    "exact Dotfiles and Zara Core checkouts not provided",
)
class NixBashZaraCoreE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for Zara Core expert E2E")
        _checkout_head(
            cls.dotfiles_root,
            EXPECTED_DOTFILES_COMMIT,
            "Dotfiles producer",
        )
        _checkout_head(
            cls.zara_core_root,
            EXPECTED_ZARA_CORE_COMMIT,
            "Zara Core",
        )

        cls.nix_source = (
            cls.dotfiles_root / ".zara" / "experts" / "nix" / "kb" / "expert.pl"
        )
        cls.bash_source = (
            cls.dotfiles_root / ".zara" / "experts" / "bash" / "kb" / "expert.pl"
        )
        for source in (cls.nix_source, cls.bash_source):
            if not source.is_file():
                raise AssertionError(f"missing canonical expert source: {source}")

    def _host_and_descriptors(self):
        sources = {
            "nix": [self.nix_source],
            "bash": [self.bash_source],
        }
        validate_language_source_contracts(sources)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        host = ExpertHost(
            SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
        )
        registered = register_language_family(host, sources)
        self.assertEqual(registered, frozenset({"nix", "bash"}))
        published = {item["expert_id"]: item for item in descriptors(registered)}
        return host, published

    def _core_registry(self, host, published, expert_id: str, handler=None):
        descriptor = ExpertDescriptor.from_wire(published[expert_id])
        registry = ExpertRegistry(engines=("swipl",))
        core_handler = handler or make_language_expert_handler(host, expert_id)
        registration = registry.register(descriptor, core_handler)
        self.assertEqual(registration["expert_id"], expert_id)
        handle, receipt = registry.activate(
            "nix-bash-e2e",
            "workspace:nix-bash-e2e",
            expert_id,
            expected_registry_generation=registry.generation,
            expected_runtime_generation=registry.runtime_generation,
        )
        self.assertEqual(receipt["state"], "active")
        return registry, descriptor, handle, core_handler

    def test_real_brains_cross_core_activation_invoke_and_effect_fence(self) -> None:
        host, published = self._host_and_descriptors()
        cases = (
            ("zara:expert/nix", "{ x = 1; }"),
            ("zara:expert/bash", "printf '%s\\n' ok"),
        )
        for expert_id, source in cases:
            with self.subTest(expert_id=expert_id):
                registry, _descriptor, handle, _handler = self._core_registry(
                    host,
                    published,
                    expert_id,
                )
                result = registry.invoke(
                    handle,
                    "inspect",
                    {
                        "source": source,
                        "source_generation": "generation-7",
                    },
                    limits=ExpertLimits(max_model_calls=0),
                    request_id=f"req:{expert_id.rsplit('/', 1)[-1]}:inspect",
                )
                self.assertIs(result.verdict, ExpertVerdict.SUCCEEDED)
                self.assertEqual(result.usage, {"model_calls": 0})
                self.assertEqual(result.effect_receipts, ())
                self.assertEqual(
                    result.resolved_registry_generation,
                    registry.generation,
                )
                self.assertEqual(
                    result.resolved_runtime_generation,
                    registry.runtime_generation,
                )

                style = registry.invoke(
                    handle,
                    "style.rules",
                    {
                        "source": source,
                        "project_style": "style:project-v1",
                    },
                    limits=ExpertLimits(max_model_calls=0),
                    request_id=f"req:{expert_id.rsplit('/', 1)[-1]}:style",
                )
                self.assertIs(style.verdict, ExpertVerdict.SUCCEEDED)
                self.assertEqual(style.usage, {"model_calls": 0})
                self.assertEqual(style.effect_receipts, ())

                blocked = registry.invoke(
                    handle,
                    "repair.apply",
                    {
                        "repair": {"kind": "preview-only"},
                        "expected_preimage": source,
                        "source_generation": "generation-7",
                    },
                    limits=ExpertLimits(max_model_calls=0),
                    request_id=f"req:{expert_id.rsplit('/', 1)[-1]}:repair",
                )
                self.assertIs(blocked.verdict, ExpertVerdict.BLOCKED)
                self.assertEqual(blocked.usage, {"model_calls": 0})
                self.assertEqual(blocked.effect_receipts, ())
                self.assertEqual(
                    blocked.data["reason"],
                    "canonical-typed-edit-required",
                )

    def test_cancellation_fences_late_real_brain_output(self) -> None:
        host, published = self._host_and_descriptors()
        expert_id = "zara:expert/nix"
        real_handler = make_language_expert_handler(host, expert_id)
        started = threading.Event()
        release = threading.Event()

        def blocking_handler(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            started.set()
            if not release.wait(timeout=10):
                raise RuntimeError("test release timed out")
            return real_handler(expert_operation=expert_operation, **payload)

        registry, _descriptor, handle, _handler = self._core_registry(
            host,
            published,
            expert_id,
            handler=blocking_handler,
        )
        outcome: dict[str, Any] = {}

        def invoke() -> None:
            try:
                outcome["result"] = registry.invoke(
                    handle,
                    "inspect",
                    {
                        "source": "{ x = 1; }",
                        "source_generation": "generation-7",
                    },
                    limits=ExpertLimits(max_model_calls=0),
                    request_id="req:nix:cancel",
                )
            except BaseException as error:  # noqa: BLE001
                outcome["error"] = error

        thread = threading.Thread(target=invoke, daemon=True)
        thread.start()
        self.assertTrue(started.wait(timeout=5), "Core never dispatched the real brain")
        invocation_ids = registry.snapshot().invocation_ids
        self.assertEqual(len(invocation_ids), 1)
        cancel_receipt = registry.cancel(invocation_ids[0])
        self.assertTrue(cancel_receipt["cancelled"])
        self.assertFalse(cancel_receipt["committed"])
        release.set()
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), "cancelled invocation did not terminate")
        self.assertNotIn("error", outcome)
        result = outcome["result"]
        self.assertIs(result.verdict, ExpertVerdict.CANCELLED)
        self.assertEqual(result.usage, {"model_calls": 0})
        self.assertEqual(result.effect_receipts, ())

    def test_generation_change_rejects_late_real_brain_success(self) -> None:
        host, published = self._host_and_descriptors()
        expert_id = "zara:expert/bash"
        real_handler = make_language_expert_handler(host, expert_id)
        started = threading.Event()
        release = threading.Event()

        def blocking_handler(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            started.set()
            if not release.wait(timeout=10):
                raise RuntimeError("test release timed out")
            return real_handler(expert_operation=expert_operation, **payload)

        registry, descriptor, handle, _handler = self._core_registry(
            host,
            published,
            expert_id,
            handler=blocking_handler,
        )
        outcome: dict[str, Any] = {}

        def invoke() -> None:
            try:
                outcome["result"] = registry.invoke(
                    handle,
                    "inspect",
                    {
                        "source": "printf '%s\\n' ok",
                        "source_generation": "generation-7",
                    },
                    limits=ExpertLimits(max_model_calls=0),
                    request_id="req:bash:stale",
                )
            except BaseException as error:  # noqa: BLE001
                outcome["error"] = error

        thread = threading.Thread(target=invoke, daemon=True)
        thread.start()
        self.assertTrue(started.wait(timeout=5), "Core never dispatched the real brain")

        replacement_handler = make_language_expert_handler(host, expert_id)
        old_generation = registry.generation
        registry.reload(((descriptor, replacement_handler),))
        self.assertGreater(registry.generation, old_generation)
        release.set()
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive(), "stale invocation did not terminate")
        self.assertNotIn("result", outcome)
        self.assertIsInstance(outcome.get("error"), ExpertStaleGenerationError)


if __name__ == "__main__":
    unittest.main()
