import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_mobility.domain import MobilityError
from zara_mobility.plugin import ZaraMobilityPlugin


class Runtime:
    def __init__(self, configuration):
        self.configuration = configuration


class MobilityPluginTest(unittest.TestCase):
    def test_configuration_controls_rideshare_availability(self):
        plugin = ZaraMobilityPlugin()
        plugin.start(
            Runtime(
                {
                    "plugins": {
                        "zara-mobility": {
                            "uber_client_id": "uber-test",
                            "lyft_client_id": "lyft-test",
                        }
                    }
                }
            )
        )
        options = json.loads(plugin.rideshare_options())
        self.assertTrue(all(item["handoff_available"] for item in options))

    def test_bad_routing_endpoint_fails_closed(self):
        plugin = ZaraMobilityPlugin()
        with self.assertRaisesRegex(MobilityError, "must use https"):
            plugin.start(
                Runtime(
                    {
                        "plugins": {
                            "zara-mobility": {
                                "osm_routing_endpoint": "http://router.invalid",
                            }
                        }
                    }
                )
            )

    def test_tool_names_are_stable(self):
        names = {tool.name for tool in ZaraMobilityPlugin().tools()}
        self.assertEqual(
            names,
            {
                "mobility.status",
                "mobility.search_places",
                "mobility.route",
                "mobility.show",
                "mobility.transit.profile",
                "mobility.rideshare.options",
                "mobility.rideshare.handoff",
                "mobility.trip_plan",
                "mobility.navigation.status",
            },
        )

    def test_status_does_not_claim_live_backends(self):
        status = json.loads(ZaraMobilityPlugin().status())
        self.assertEqual(status["live_transit_parsing"], "follow_on")
        self.assertFalse(status["navigation"]["available"])


if __name__ == "__main__":
    unittest.main()
