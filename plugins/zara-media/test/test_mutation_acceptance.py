import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_media.domain import MediaDomain


ITEM = {
    "media_id": "track-1",
    "kind": "track",
    "title": "One",
    "artist": "Ada",
    "show": None,
    "duration_ms": 1000,
    "provider": "test",
}


class MalformedAcceptanceBackend:
    def __init__(self):
        self.items = [dict(ITEM)]

    def list_players(self):
        return [{
            "player_id": "desk",
            "name": "Desk",
            "device": "headphones",
            "state": "stopped",
            "volume": 0.5,
            "muted": False,
            "position_ms": 0,
            "item": None,
        }]

    def active_player_id(self):
        return "desk"

    def set_active_player(self, player_id):
        return {"accepted": "false"}

    def queue(self, player_id):
        return [dict(item) for item in self.items]

    def queue_add(self, player_id, item):
        self.items.append(dict(item))
        return {"accepted": "false"}

    def queue_move(self, player_id, source_index, destination_index):
        item = self.items.pop(source_index)
        self.items.insert(destination_index, item)
        return {"accepted": "false"}


class MediaMutationAcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.backend = MalformedAcceptanceBackend()
        self.media = MediaDomain(self.backend)

    def test_select_player_rejects_truthy_non_boolean_acceptance(self):
        result = self.media.select_player("desk")
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])

    def test_queue_add_rejects_truthy_non_boolean_acceptance(self):
        second = dict(ITEM, media_id="track-2", title="Two")
        result = self.media.queue_add("desk", second)
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])

    def test_queue_move_rejects_truthy_non_boolean_acceptance(self):
        self.backend.items.append(dict(ITEM, media_id="track-2", title="Two"))
        result = self.media.queue_move("desk", 0, 1)
        self.assertFalse(result["accepted"])
        self.assertFalse(result["verified"])


if __name__ == "__main__":
    unittest.main()
