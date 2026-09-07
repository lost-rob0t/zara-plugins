import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_media.domain import MediaDomain, MediaError


ITEM = {
    "media_id": "track-1",
    "kind": "track",
    "title": "One",
    "artist": "Ada",
    "show": None,
    "duration_ms": 1000,
    "provider": "test",
}

PLAYER = {
    "player_id": "desk",
    "name": "Desk",
    "device": "headphones",
    "state": "stopped",
    "volume": 0.5,
    "muted": False,
    "position_ms": 0,
    "item": None,
}


class MediaNumericMetadataTypeTest(unittest.TestCase):
    def test_duration_rejects_coercible_non_integers(self):
        for malformed in (True, "1000", 1.5):
            with self.subTest(duration_ms=malformed):
                with self.assertRaisesRegex(MediaError, "duration"):
                    MediaDomain._item(dict(ITEM, duration_ms=malformed))

    def test_position_rejects_coercible_non_integers(self):
        for malformed in (True, "1000", 1.5):
            with self.subTest(position_ms=malformed):
                with self.assertRaisesRegex(MediaError, "position"):
                    MediaDomain._player(dict(PLAYER, position_ms=malformed))

    def test_volume_rejects_coercible_non_numeric_values(self):
        for malformed in (True, "0.5"):
            with self.subTest(volume=malformed):
                with self.assertRaisesRegex(MediaError, "volume"):
                    MediaDomain._player(dict(PLAYER, volume=malformed))


if __name__ == "__main__":
    unittest.main()
