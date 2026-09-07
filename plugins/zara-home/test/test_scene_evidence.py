import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_home.domain import HomeService


class MalformedSceneProvider:
    def activate_scene(self, scene_id):
        return {"verified": "false", "scene_id": scene_id}


class HomeSceneEvidenceTest(unittest.TestCase):
    def test_truthy_non_boolean_verification_fails_closed(self):
        result = HomeService(MalformedSceneProvider()).activate_scene("scene-1")
        self.assertFalse(result["verified"])
        self.assertEqual(result["provider_evidence"]["verified"], "false")


if __name__ == "__main__":
    unittest.main()
