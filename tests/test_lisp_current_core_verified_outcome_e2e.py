import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CORE_ROOT = os.environ.get("ZARA_CORE_ROOT")
EXPECTED_DOTFILES_COMMIT = "3309c54ecb5f65c29374de6c60d2135a9ea2f94b"
EXPECTED_ZARA_CORE_COMMIT = "29aaaab83ff2ebb27f483c47e43403c1fc252574"
ZARA_EXPERT_LIB = REPO_ROOT / "plugins" / "zara-expert" / "lib"

if ZARA_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CORE_ROOT).resolve()))
sys.path.insert(0, str(ZARA_EXPERT_LIB))

from zara_expert.backend import SwiplBackend
from zara_expert.composition import InvocationFence, MetaExpertComposer, SharedSymbolicBudget
from zara_expert.domain import ExpertHost
from zara_expert.lisp_composition import CoreLispFamilyCompositionInvoker
from zara_expert.lisp_family import descriptors, make_lisp_expert_handler, register_lisp_family
from zara_expert.lisp_source_contract import validate_lisp_source_contracts

if ZARA_CORE_ROOT:
    from zara.experts import ExpertDescriptor, ExpertLimits, ExpertRegistry


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
class LispCurrentCoreVerifiedOutcomeE2ETests(unittest.TestCase):
    WORKSPACE = "workspace:lisp-current-core-verified-outcome"

    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for Lisp current-Core E2E")
        _checkout_head(cls.dotfiles_root, EXPECTED_DOTFILES_COMMIT, "Dotfiles producer")
        _checkout_head(cls.zara_core_root, EXPECTED_ZARA_CORE_COMMIT, "Zara Core")
        cls.sources = {
            key: [
                cls.dotfiles_root
                / ".zara"
                / "experts"
                / key
                / "kb"
                / "expert.pl"
            ]
            for key in ("lisp", "common-lisp", "emacs-lisp")
        }
        for paths in cls.sources.values():
            for source in paths:
                if not source.is_file():
                    raise AssertionError(f"missing canonical Lisp source: {source}")
        validate_lisp_source_contracts(cls.sources)

    def _runtime(self, verified_outcome_resolver):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        host = ExpertHost(
            SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
            query_timeout_seconds=5.0,
        )
        registered = register_lisp_family(host, self.sources)
        self.assertEqual(
            registered,
            frozenset({"lisp", "common-lisp", "emacs-lisp"}),
        )
        published = {item["expert_id"]: item for item in descriptors(registered)}
        registry = ExpertRegistry(engines=("swipl",))
        for expert_id in (
            "zara:expert/lisp",
            "zara:expert/common-lisp",
            "zara:expert/emacs-lisp",
        ):
            registry.register(
                ExpertDescriptor.from_wire(published[expert_id]),
                make_lisp_expert_handler(
                    host,
                    expert_id,
                    verified_outcome_resolver=verified_outcome_resolver,
                ),
            )

        handles = {}
        for expert_id in published:
            if expert_id not in {
                "zara:expert/lisp",
                "zara:expert/common-lisp",
                "zara:expert/emacs-lisp",
            }:
                continue
            handle, receipt = registry.activate(
                "expert-builder-1",
                self.WORKSPACE,
                expert_id,
                expected_registry_generation=registry.generation,
                expected_runtime_generation=registry.runtime_generation,
            )
            self.assertEqual(receipt["state"], "active")
            handles[expert_id] = handle
        return registry, handles

    def _fence(self) -> InvocationFence:
        return InvocationFence(
            workspace_id=self.WORKSPACE,
            workspace_generation=1,
            is_cancelled=lambda: False,
            is_current_generation=lambda workspace, generation: (
                workspace == self.WORKSPACE and generation == 1
            ),
        )

    def _composer(self, registry, handles):
        def activation_for(expert_id, fence):
            self.assertEqual(fence.workspace_id, self.WORKSPACE)
            return handles[expert_id]

        return MetaExpertComposer(
            CoreLispFamilyCompositionInvoker(
                registry,
                activation_for=activation_for,
                limits_factory=ExpertLimits,
            )
        )

    def _trace_for(self, registry, expert_id: str):
        matches = []
        for invocation_id in registry.snapshot().invocation_ids:
            trace = registry.explain(invocation_id)
            if trace.get("expert_id") == expert_id:
                matches.append(trace)
        self.assertEqual(len(matches), 1)
        return matches[0]

    def test_fresh_dialect_receipt_promotes_real_verify_through_current_core(self) -> None:
        receipts = {}
        resolver_calls = []

        def resolve_verified_outcome(**lookup):
            resolver_calls.append(dict(lookup))
            key = (
                lookup.get("expert_id"),
                lookup.get("source_generation"),
                lookup.get("candidate_sha256"),
                lookup.get("required_postcondition"),
            )
            return receipts.get(key)

        registry, handles = self._runtime(resolve_verified_outcome)
        composer = self._composer(registry, handles)
        candidate = "(defun demo (x) (list x))"
        candidate_sha256 = hashlib.sha256(candidate.encode("utf-8")).hexdigest()

        cases = (
            (
                "zara:expert/common-lisp",
                "buffer:common-lisp:42",
                "sbcl_fresh_reader_and_compile_evidence",
                "zara.verified-outcome/v1:outcome:postcondition/common-lisp-buffer-42",
            ),
            (
                "zara:expert/emacs-lisp",
                "buffer:emacs-lisp:42",
                "emacs_fresh_reader_and_byte_compile_evidence",
                "zara.verified-outcome/v1:outcome:postcondition/emacs-lisp-buffer-42",
            ),
        )

        for expert_id, source_generation, postcondition, receipt_ref in cases:
            with self.subTest(expert=expert_id):
                lookup = {
                    "expert_id": expert_id,
                    "source_generation": source_generation,
                    "candidate_sha256": candidate_sha256,
                    "required_postcondition": postcondition,
                }
                receipts[(
                    expert_id,
                    source_generation,
                    candidate_sha256,
                    postcondition,
                )] = {
                    **lookup,
                    "receipt_ref": receipt_ref,
                    "verified": True,
                    "fresh": True,
                }

                budget = SharedSymbolicBudget(max_model_calls=0)
                tree = composer.invoke(
                    expert_id,
                    "repair.verify",
                    {
                        "arguments": [
                            "(defun demo (x) (list x",
                            candidate,
                        ],
                        "source_generation": source_generation,
                    },
                    budget=budget,
                    fence=self._fence(),
                )

                self.assertEqual(tree.status, "succeeded")
                self.assertIs(tree.data["verified"], True)
                self.assertEqual(tree.data["verified_outcome_ref"], receipt_ref)
                self.assertEqual(
                    tree.data["postcondition_evidence"],
                    {
                        "receipt_ref": receipt_ref,
                        "required_postcondition": postcondition,
                        "source_generation": source_generation,
                        "candidate_sha256": candidate_sha256,
                    },
                )
                self.assertIn(receipt_ref, tree.evidence)
                self.assertEqual(resolver_calls[-1], lookup)
                self.assertEqual(budget.model_calls_used, 0)

                trace = self._trace_for(registry, expert_id)
                self.assertEqual(trace["verdict"], "succeeded")
                self.assertEqual(trace.get("effect_receipts", []), [])
                self.assertIs(type(trace["usage"]["model_calls"]), int)
                self.assertEqual(trace["usage"]["model_calls"], 0)
                self.assertIn(receipt_ref, trace["evidence_refs"])


if __name__ == "__main__":
    unittest.main()
