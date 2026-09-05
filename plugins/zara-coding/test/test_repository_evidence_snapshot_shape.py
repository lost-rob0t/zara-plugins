import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_coding.repository_evidence import build_repository_evidence


class RepositorySnapshotEvidenceShapeTests(unittest.TestCase):
    def test_rejects_non_mapping_snapshot_with_contract_error(self):
        with self.assertRaisesRegex(ValueError, "repository snapshot must be structured"):
            build_repository_evidence("not-a-snapshot")


if __name__ == "__main__":
    unittest.main()
