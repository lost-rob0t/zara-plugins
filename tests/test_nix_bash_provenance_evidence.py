from __future__ import annotations

import hashlib
import json
import unittest

from tests import test_nix_bash_result_snapshot as snapshot


_PROVENANCE_PREFIX = "evidence:expert-provenance:sha256:"


def _expected_provenance_ref(module) -> str:
    payload = {
        "expert_id": module.EXPERT_ID,
        "expert_version": module.PLUGIN_VERSION,
        "manifest_digest": module.MANIFEST_DIGEST,
        "source_reference": module.SOURCE_REFERENCE,
        "upstream_contract": module.UPSTREAM_CONTRACT,
        "zara_contract": (
            f"{module.ZARA_CONTRACT_REPOSITORY}#{module.ZARA_CONTRACT_ISSUE}"
        ),
        "zara_schema_pr": module.ZARA_CONTRACT_SCHEMA_PR,
    }
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _PROVENANCE_PREFIX + hashlib.sha256(encoded).hexdigest()


class NixBashProvenanceEvidenceTests(unittest.TestCase):
    def test_serialized_success_binds_verified_provenance_snapshot(self) -> None:
        for module, _error_type, source in snapshot.CASES:
            with self.subTest(expert_id=module.EXPERT_ID):
                expected_ref = _expected_provenance_ref(module)
                runtime = snapshot._Runtime(module)
                encoded = snapshot._invoke(module, runtime, source)
                projected = json.loads(encoded)

                self.assertEqual(
                    projected["evidence_refs"],
                    ["fixture:evidence", expected_ref],
                )
                self.assertEqual(projected["manifest_digest"], module.MANIFEST_DIGEST)
                self.assertEqual(projected["usage"], {"model_calls": 0})
                self.assertEqual(projected["effect_receipts"], [])
                self.assertEqual(
                    runtime.requests[0]["limits"]["max_model_calls"],
                    0,
                )

                original_source = module.SOURCE_REFERENCE
                original_upstream = module.UPSTREAM_CONTRACT
                try:
                    module.SOURCE_REFERENCE = original_source + "-newer"
                    module.UPSTREAM_CONTRACT = original_upstream + "-newer"
                    recovered = json.loads(encoded)
                    self.assertEqual(
                        recovered["evidence_refs"],
                        ["fixture:evidence", expected_ref],
                    )
                finally:
                    module.SOURCE_REFERENCE = original_source
                    module.UPSTREAM_CONTRACT = original_upstream


if __name__ == "__main__":
    unittest.main()
