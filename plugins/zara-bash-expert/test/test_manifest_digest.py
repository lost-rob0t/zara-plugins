from __future__ import annotations

import hashlib
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_bash_expert.plugin import SOURCE_LOCK_DIGEST


class BashExpertSourceLockDigestTests(unittest.TestCase):
    def test_source_lock_digest_pins_source_lock_bytes(self) -> None:
        lock = (ROOT / "expert-source.lock.json").read_bytes()
        expected = "sha256:" + hashlib.sha256(lock).hexdigest()
        self.assertEqual(SOURCE_LOCK_DIGEST, expected)


if __name__ == "__main__":
    unittest.main()
