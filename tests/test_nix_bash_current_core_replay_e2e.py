"""Gate Nix/Bash pure-symbolic idempotent replay through current Zara Core."""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any

from tests import test_nix_bash_current_core_delegation_e2e as current_core


DOTFILES_ROOT = os.environ.get("ZARA_DOTFILES_ROOT")
ZARA_CURRENT_CORE_ROOT = os.environ.get("ZARA_CURRENT_CORE_ROOT")

if ZARA_CURRENT_CORE_ROOT:
    sys.path.insert(0, str(Path(ZARA_CURRENT_CORE_ROOT).resolve()))
    from zara.experts import (  # noqa: E402
        ExpertDescriptor,
        ExpertInvalidInputError,
        ExpertLimits,
        ExpertRegistry,
        ExpertVerdict,
    )


@unittest.skipUnless(
    DOTFILES_ROOT and ZARA_CURRENT_CORE_ROOT,
    "exact Dotfiles and current Zara Core checkouts not provided",
)
class NixBashCurrentCoreReplayE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.dotfiles_root = Path(DOTFILES_ROOT).resolve()
        cls.zara_core_root = Path(ZARA_CURRENT_CORE_ROOT).resolve()
        if shutil.which("swipl") is None:
            raise AssertionError("SWI-Prolog is required for Nix/Bash replay E2E")
        current_core._checkout_head(
            cls.dotfiles_root,
            current_core.EXPECTED_DOTFILES_COMMIT,
            "Dotfiles producer",
        )
        current_core._checkout_head(
            cls.zara_core_root,
            current_core.EXPECTED_ZARA_CORE_COMMIT,
            "Zara Core",
        )
        cls.sources = {
            language: [
                cls.dotfiles_root
                / ".zara"
                / "experts"
                / language
                / "kb"
                / "expert.pl"
            ]
            for language in ("nix", "bash")
        }
        for source_files in cls.sources.values():
            for source in source_files:
                if not source.is_file():
                    raise AssertionError(f"missing canonical expert source: {source}")
        current_core.validate_language_source_contracts(cls.sources)

    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.host = current_core.ExpertHost(
            current_core.SwiplBackend(),
            state_root=Path(temporary.name) / "zara-expert-state",
        )
        registered = current_core.register_language_family(self.host, self.sources)
        self.assertEqual(registered, frozenset({"nix", "bash"}))
        self.published = {
            item["expert_id"]: item
            for item in current_core.descriptors(registered)
        }

    def _registry(self, expert_id: str):
        descriptor = ExpertDescriptor.from_wire(self.published[expert_id])
        real_handler = current_core.make_language_expert_handler(self.host, expert_id)
        calls: list[tuple[str, dict[str, Any]]] = []

        def counted_handler(*, expert_operation: str, **payload: Any) -> dict[str, Any]:
            calls.append((expert_operation, dict(payload)))
            return dict(real_handler(expert_operation=expert_operation, **payload))

        registry = ExpertRegistry(engines=("swipl",))
        registry.register(descriptor, counted_handler)
        handle, receipt = registry.activate(
            "user:nix-bash-replay",
            "workspace:nix-bash-replay",
            expert_id,
            expected_registry_generation=registry.generation,
            expected_runtime_generation=registry.runtime_generation,
        )
        self.assertEqual(receipt["state"], "active")
        return registry, handle, calls

    def test_real_nix_and_bash_replay_once_without_provider_or_effect_reexecution(self) -> None:
        cases = (
            ("zara:expert/nix", "{ x = 1; }"),
            ("zara:expert/bash", "printf '%s\\n' ok"),
        )
        for expert_id, source in cases:
            with self.subTest(expert_id=expert_id):
                registry, handle, calls = self._registry(expert_id)
                language = expert_id.rsplit("/", 1)[-1]
                request_id = f"req:nix-bash-replay:{language}"
                idempotency_key = f"idem:nix-bash-replay:{language}"
                payload = {
                    "source": source,
                    "source_generation": "generation-replay-e2e",
                }

                first = registry.invoke(
                    handle,
                    "inspect",
                    payload,
                    limits=ExpertLimits(max_model_calls=0),
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                )
                replay = registry.invoke(
                    handle,
                    "inspect",
                    payload,
                    limits=ExpertLimits(max_model_calls=0),
                    request_id=request_id,
                    idempotency_key=idempotency_key,
                )

                self.assertIs(first.verdict, ExpertVerdict.SUCCEEDED)
                self.assertIs(first.replayed, False)
                self.assertIs(replay.verdict, ExpertVerdict.SUCCEEDED)
                self.assertIs(replay.replayed, True)
                self.assertEqual(replay.invocation_id, first.invocation_id)
                self.assertEqual(replay.request_id, first.request_id)
                self.assertEqual(replay.data, first.data)
                self.assertEqual(replay.evidence_refs, first.evidence_refs)
                self.assertEqual(first.usage, {"model_calls": 0})
                self.assertEqual(replay.usage, {"model_calls": 0})
                self.assertEqual(first.effect_receipts, ())
                self.assertEqual(replay.effect_receipts, ())
                self.assertEqual(len(calls), 1, "replay re-dispatched the real brain")
                self.assertEqual(registry.snapshot().invocation_ids, (first.invocation_id,))

                with self.assertRaisesRegex(
                    ExpertInvalidInputError,
                    "idempotency",
                ):
                    registry.invoke(
                        handle,
                        "inspect",
                        {
                            "source": source + " ",
                            "source_generation": "generation-replay-e2e",
                        },
                        limits=ExpertLimits(max_model_calls=0),
                        request_id=request_id,
                        idempotency_key=idempotency_key,
                    )
                self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
