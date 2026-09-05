import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.domain import CodingError
from zara_coding.spec_verify import _repository_payload


class VerificationEvidenceShapeTests(unittest.TestCase):
    def test_rejects_non_mapping_evidence_with_contract_error(self):
        with self.assertRaisesRegex(CodingError, "repository evidence must be structured"):
            _repository_payload("not-evidence")


if __name__ == "__main__":
    unittest.main()
