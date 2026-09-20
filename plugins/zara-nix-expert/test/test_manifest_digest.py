from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_nix_expert.plugin import MANIFEST_DIGEST


class NixExpertManifestDigestTests(unittest.TestCase):
    def test_manifest_digest_pins_source_lock_bytes(self) -> None:
        lock = (ROOT / "expert-source.lock.json").read_bytes()
        expected = "sha256:" + hashlib.sha256(lock).hexdigest()
        self.assertEqual(MANIFEST_DIGEST, expected)


if __name__ == "__main__":
    unittest.main()
