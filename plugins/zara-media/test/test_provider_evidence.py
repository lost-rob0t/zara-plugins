import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_media.domain import MediaDomain, MediaError


class MalformedEvidenceBackend:
    def __init__(self):
        self.player = {
            "player_id": "desk",
            "name": "Desk",
            "device": "headphones",
            "state": "playing",
            "volume": 0.5,
            "muted": False,
            "position_ms": 0,
            "item": None,
        }

    def list_players(self):
        return [dict(self.player)]

    def player_state(self, player_id):
        return dict(self.player)

    def playback_action(self, player_id, action, value=None):
        if action == "pause":
            self.player["state"] = "paused"
        return {"accepted": "false"}

    def active_player_id(self):
        return "desk"


class ProviderEvidenceTest(unittest.TestCase):
    def test_non_boolean_acceptance_evidence_fails_closed(self):
        media = MediaDomain(MalformedEvidenceBackend())
        with self.assertRaises(MediaError):
            media.playback("desk", "pause")

    def test_non_boolean_muted_observation_fails_closed(self):
        backend = MalformedEvidenceBackend()
        backend.player["muted"] = "false"
        media = MediaDomain(backend)
        with self.assertRaises(MediaError):
            media.state("desk")


if __name__ == "__main__":
    unittest.main()
