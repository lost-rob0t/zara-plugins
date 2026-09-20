from __future__ import annotations

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
ZARA_CURRENT_CORE_ROOT = os.environ.get("ZARA_CURRENT_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "1b93e01f3482e49a853f651eb28c21eb1d9cad0e"
EXPECTED_ZARA_CORE_COMMIT = "36e6d48fa750f30b5493f0c2acc789f3e9300e97"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"

if ZARA_CURRENT_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CURRENT_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.domain import ExpertHost
from zara_expert.language_family import descriptors, register_language_family
from zara_expert.language_handler import make_language_expert_handler
from zara_expert.language_source_contract import validate_language_source_contracts

if ZARA_CURRENT_CORE_ROOT:
    from zara.experts import (
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


def _parent_descriptor() -> ExpertDescriptor:
    return ExpertDescriptor.from_wire(
        {
            "protocol": "ZARA-EXPERT/1",
            "expert_id": "zara:expert/nix-bash-current-core-parent",
            "expert_version": "1.0.0",
            "package_namespace": "zara-plugins-e2e",
            "manifest_digest": "sha256:nix-bash-current-core-parent.v1",
            "name": "NixBashCurrentCoreParent",
            "description": "Pure-symbolic parent proving current Core nested delegation.",
            "source_reference": "tests/test_nix_bash_current_core_delegation_e2e.py",
            "reasoning_kind": "symbolic",
            "operations": [
                {
                    "operation_id": "inspect",
                    "input_schema": {
                        "fields": [
                            {"name": "language", "type": "string", "required": True},
                            {"name": "source", "type": "string", "required": True},
                        ]
                    },
                    "output_schema": {"fields": []},
                }
            ],
            "applicability": {"keywords": ["nix", "bash"]},
            "required_capabilities": [],
            "possible_effects": ["none"],
            "supported_engines": [],
            "supported_platforms": ["linux"],
            "fallback_policy": "fail_closed",
            "delegation_policy": "children",
            "resource_limits": {"max_model_calls": 0},
            "registry_generation": 0,
            "availability": "ready",
        }
    )


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CURRENT_CORE_ROOT,
    "exact Dotfiles and current Zara Core checkouts not provided",
)
class NixBashCurrentCoreDelegationE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CURRENT_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for current Core delegation E2E")
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT, "Dotfiles producer")
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "Zara Core")
        cls.sources = {
            "nix": [
                cls.dotfiles_root / ".zara" / "experts" / "nix" / "kb" / "expert.pl"
            ],
            "bash": [
                cls.dotfiles_root / ".zara" / "experts" / "bash" / "kb" / "expert.pl"
            ],
        }
        for source_files in cls.sources.values():
            for source in source_files:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")
        validate_language_source_contracts(cls.sources)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.host = ExpertHost(
            SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
        )
        registered = register_language_family(self.host, self.sources)
        self.assertEqual(registered, frozenset({"nix", "bash"}))
        self.published = {item["expert_id"]: item for item in descriptors(registered)}

    def test_real_nix_and_bash_children_inherit_parent_zero_model_budget(self) -> None:
        registry = ExpertRegistry(engines=("swipl",))
        handles: dict[str, Any] = {}

        class Parent:
            def __call__(parent_self, *, expert_operation: str, **payload: Any) -> dict[str, Any]:
                self.assertEqual(expert_operation, "inspect")
                language = payload["language"]
                expert_id = f"zara:expert/{language}"
                child = registry.invoke(
                    handles[expert_id],
                    "inspect",
                    {
                        "source": payload["source"],
                        "source_generation": "generation-current-core",
                    },
                    # Deliberately asks to widen. Current Core must intersect this
                    # with the active parent's shared max_model_calls=0 authority.
                    limits=ExpertLimits(max_model_calls=64),
                    request_id=f"req:current-core:{language}:child",
                )
                return {
                    "verdict": "succeeded",
                    "data": {
                        "child_expert_id": expert_id,
                        "child_verdict": child.verdict.value,
                        "child_model_calls": child.usage["model_calls"],
                        "child_effect_receipts": list(child.effect_receipts),
                    },
                    "evidence_refs": [
                        f"ev:current-core:{language}:delegated",
                        *child.evidence_refs,
                    ],
                    "usage": {"model_calls": 0},
                    "effect_receipts": [],
                }

        registry.register(_parent_descriptor(), Parent())
        for expert_id in ("zara:expert/nix", "zara:expert/bash"):
            descriptor = ExpertDescriptor.from_wire(self.published[expert_id])
            registry.register(
                descriptor,
                make_language_expert_handler(self.host, expert_id),
            )

        principal = "user:nix-bash-current-core"
        workspace = "workspace:nix-bash-current-core"
        parent_handle, _ = registry.activate(
            principal,
            workspace,
            "zara:expert/nix-bash-current-core-parent",
        )
        for expert_id in ("zara:expert/nix", "zara:expert/bash"):
            handles[expert_id], _ = registry.activate(principal, workspace, expert_id)

        cases = (
            ("nix", "{ x = 1; }"),
            ("bash", "printf '%s\\n' ok"),
        )
        for language, source in cases:
            with self.subTest(language=language):
                result = registry.invoke(
                    parent_handle,
                    "inspect",
                    {"language": language, "source": source},
                    limits=ExpertLimits(max_model_calls=0),
                    request_id=f"req:current-core:{language}:parent",
                )
                self.assertIs(result.verdict, ExpertVerdict.SUCCEEDED)
                self.assertEqual(result.data["child_expert_id"], f"zara:expert/{language}")
                self.assertEqual(result.data["child_verdict"], "succeeded")
                self.assertEqual(result.data["child_model_calls"], 0)
                self.assertEqual(result.data["child_effect_receipts"], [])
                self.assertEqual(result.usage, {"model_calls": 0})
                self.assertEqual(result.effect_receipts, ())


if __name__ == "__main__":
    unittest.main()
