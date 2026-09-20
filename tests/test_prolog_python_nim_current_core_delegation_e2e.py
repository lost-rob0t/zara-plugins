import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "1c825e84a4ca2eaee6fa9a7db8c251b256d991c9"
EXPECTED_ZARA_CORE_COMMIT = "c99dd6c68fecfd8f346429532a750c9c2e6bf65d"
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
        ExpertDeniedError,
        ExpertDescriptor,
        ExpertLimits,
        ExpertRegistry,
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
class PrologPythonNimCurrentCoreDelegationE2ETests(unittest.TestCase):
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

    def _language_runtime(self):
        validate_language_source_contracts(self.sources)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        host = ExpertHost(
            SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
        )
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
        return published, handlers

    @staticmethod
    def _activate(
        registry,
        expert_id: str,
        *,
        workspace: str = "workspace:prolog-python-nim-current-core",
    ):
        handle, receipt = registry.activate(
            "expert-builder-3",
            workspace,
            expert_id,
            expected_registry_generation=registry.generation,
            expected_runtime_generation=registry.runtime_generation,
        )
        if receipt["state"] != "active":
            raise AssertionError(f"failed to activate {expert_id}: {receipt!r}")
        return handle

    def test_real_language_parent_delegates_to_real_children_under_one_zero_model_budget(
        self,
    ) -> None:
        published, handlers = self._language_runtime()
        registry = ExpertRegistry(engines=("swipl",))
        child_handles: dict[str, Any] = {}
        observed: list[tuple[str, str, int]] = []
        prolog_handler = handlers["zara:expert/prolog"]

        def delegating_prolog(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            parent_result = prolog_handler(
                expert_operation=expert_operation,
                **payload,
            )
            child_cases = (
                (
                    "zara:expert/python",
                    "def answer():\n    return 42\n",
                    "generation-python-current-core",
                ),
                (
                    "zara:expert/nim",
                    "proc answer(): int = 42\n",
                    "generation-nim-current-core",
                ),
            )
            for expert_id, source, generation in child_cases:
                child_result = registry.invoke(
                    child_handles[expert_id],
                    "inspect",
                    {
                        "source": source,
                        "source_generation": generation,
                    },
                    limits=ExpertLimits(max_model_calls=64),
                )
                observed.append(
                    (
                        expert_id,
                        child_result.verdict.value,
                        child_result.usage["model_calls"],
                    )
                )
            return parent_result

        for expert_id in (
            "zara:expert/prolog",
            "zara:expert/python",
            "zara:expert/nim",
        ):
            descriptor = ExpertDescriptor.from_wire(published[expert_id])
            handler = delegating_prolog if expert_id == "zara:expert/prolog" else handlers[expert_id]
            registry.register(descriptor, handler)

        parent_handle = self._activate(registry, "zara:expert/prolog")
        child_handles["zara:expert/python"] = self._activate(
            registry,
            "zara:expert/python",
        )
        child_handles["zara:expert/nim"] = self._activate(
            registry,
            "zara:expert/nim",
        )

        result = registry.invoke(
            parent_handle,
            "inspect",
            {
                "source": "fact(a).",
                "source_generation": "generation-prolog-current-core",
            },
            limits=ExpertLimits(max_model_calls=0),
        )

        self.assertIs(result.verdict, ExpertVerdict.SUCCEEDED)
        self.assertEqual(
            observed,
            [
                ("zara:expert/python", "succeeded", 0),
                ("zara:expert/nim", "succeeded", 0),
            ],
        )
        self.assertIs(type(result.usage["model_calls"]), int)
        self.assertEqual(result.usage["model_calls"], 0)
        self.assertEqual(len(registry.snapshot().invocation_ids), 3)

    def test_real_language_delegation_cannot_cross_workspace_or_reach_child_backend(
        self,
    ) -> None:
        published, handlers = self._language_runtime()
        registry = ExpertRegistry(engines=("swipl",))
        child_handle_box: dict[str, Any] = {}
        python_calls = 0
        blocked = False
        prolog_handler = handlers["zara:expert/prolog"]
        python_handler = handlers["zara:expert/python"]

        def counted_python(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            nonlocal python_calls
            python_calls += 1
            return python_handler(expert_operation=expert_operation, **payload)

        def delegating_prolog(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            nonlocal blocked
            parent_result = prolog_handler(expert_operation=expert_operation, **payload)
            try:
                registry.invoke(
                    child_handle_box["handle"],
                    "inspect",
                    {
                        "source": "def answer():\n    return 42\n",
                        "source_generation": "generation-python-other-workspace",
                    },
                    limits=ExpertLimits(max_model_calls=64),
                )
            except ExpertDeniedError:
                blocked = True
            return parent_result

        registry.register(
            ExpertDescriptor.from_wire(published["zara:expert/prolog"]),
            delegating_prolog,
        )
        registry.register(
            ExpertDescriptor.from_wire(published["zara:expert/python"]),
            counted_python,
        )
        registry.register(
            ExpertDescriptor.from_wire(published["zara:expert/nim"]),
            handlers["zara:expert/nim"],
        )

        parent_handle = self._activate(registry, "zara:expert/prolog")
        child_handle_box["handle"] = self._activate(
            registry,
            "zara:expert/python",
            workspace="workspace:other",
        )

        result = registry.invoke(
            parent_handle,
            "inspect",
            {
                "source": "fact(a).",
                "source_generation": "generation-prolog-cross-workspace",
            },
            limits=ExpertLimits(max_model_calls=0),
        )

        self.assertIs(result.verdict, ExpertVerdict.SUCCEEDED)
        self.assertTrue(blocked)
        self.assertEqual(python_calls, 0)
        self.assertIs(type(result.usage["model_calls"]), int)
        self.assertEqual(result.usage["model_calls"], 0)
        self.assertEqual(len(registry.snapshot().invocation_ids), 1)


if __name__ == "__main__":
    unittest.main()
