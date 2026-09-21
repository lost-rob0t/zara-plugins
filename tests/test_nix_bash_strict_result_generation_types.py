from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "plugins" / "zara-nix-expert" / "lib"))
sys.path.insert(0, str(REPO_ROOT / "plugins" / "zara-bash-expert" / "lib"))

from zara_bash_expert.plugin import (
    BashExpertAdapterError,
    EXPERT_ID as BASH_EXPERT_ID,
    MANIFEST_DIGEST as BASH_MANIFEST_DIGEST,
    _validate_result as validate_bash_result,
)
from zara_nix_expert.plugin import (
    EXPERT_ID as NIX_EXPERT_ID,
    MANIFEST_DIGEST as NIX_MANIFEST_DIGEST,
    NixExpertAdapterError,
    _validate_result as validate_nix_result,
)


REQUEST_ID = "req-generation-type"
ACTIVATION_ID = "act:" + ("c" * 32)
EXPERT_OPERATION = "parse"
EXPECTED_GENERATION = 1


def _result(
    *,
    expert_id: str,
    manifest_digest: str,
    registry_generation: object = EXPECTED_GENERATION,
    runtime_generation: object = EXPECTED_GENERATION,
) -> dict[str, object]:
    return {
        "protocol": "ZARA-EXPERT/1",
        "request_id": REQUEST_ID,
        "invocation_id": "inv:generation-type",
        "activation_id": ACTIVATION_ID,
        "expert_id": expert_id,
        "expert_version": "0.1.0",
        "manifest_digest": manifest_digest,
        "expert_operation": EXPERT_OPERATION,
        "resolved_registry_generation": registry_generation,
        "resolved_runtime_generation": runtime_generation,
        "verdict": "succeeded",
        "data": {"verdict": "clean"},
        "evidence_refs": [],
        "usage": {"model_calls": 0},
        "effect_receipts": [],
    }


class StrictResultGenerationTypeTests(unittest.TestCase):
    def _assert_boolean_generation_rejected(
        self,
        *,
        validate,
        error_type,
        expert_id: str,
        manifest_digest: str,
    ) -> None:
        cases = (
            {"registry_generation": True},
            {"runtime_generation": True},
        )
        for mutation in cases:
            with self.subTest(expert_id=expert_id, mutation=mutation):
                result = _result(
                    expert_id=expert_id,
                    manifest_digest=manifest_digest,
                    **mutation,
                )
                with self.assertRaisesRegex(error_type, "stale-expert-result"):
                    validate(
                        result,
                        request_id=REQUEST_ID,
                        activation_id=ACTIVATION_ID,
                        expert_operation=EXPERT_OPERATION,
                        registry_generation=EXPECTED_GENERATION,
                        runtime_generation=EXPECTED_GENERATION,
                    )

    def test_nix_result_boolean_generations_fail_closed(self) -> None:
        self._assert_boolean_generation_rejected(
            validate=validate_nix_result,
            error_type=NixExpertAdapterError,
            expert_id=NIX_EXPERT_ID,
            manifest_digest=NIX_MANIFEST_DIGEST,
        )

    def test_bash_result_boolean_generations_fail_closed(self) -> None:
        self._assert_boolean_generation_rejected(
            validate=validate_bash_result,
            error_type=BashExpertAdapterError,
            expert_id=BASH_EXPERT_ID,
            manifest_digest=BASH_MANIFEST_DIGEST,
        )


if __name__ == "__main__":
    unittest.main()
