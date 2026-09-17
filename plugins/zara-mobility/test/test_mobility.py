import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_mobility.domain import MobilityDomain, MobilityError


class MobilityDomainTest(unittest.TestCase):
    def test_google_search_uses_api_one_and_preserves_query(self):
        domain = MobilityDomain()
        result = domain.google_search("coffee & tea")
        parsed = urlparse(result["url"])
        query = parse_qs(parsed.query)
        self.assertEqual(result["provider"], "google_maps")
        self.assertEqual(result["action"], "search")
        self.assertEqual(query["api"], ["1"])
        self.assertEqual(query["query"], ["coffee & tea"])

    def test_google_directions_preserves_ordered_waypoints_and_closed_modes(self):
        domain = MobilityDomain()
        result = domain.google_directions(
            destination="C",
            origin="Home",
            travel_mode="walking",
            waypoints=["A", "B"],
            avoid=["tolls", "ferries"],
        )
        query = parse_qs(urlparse(result["url"]).query)
        self.assertEqual(query["origin"], ["Home"])
        self.assertEqual(query["destination"], ["C"])
        self.assertEqual(query["waypoints"], ["A|B"])
        self.assertEqual(query["travelmode"], ["walking"])
        self.assertEqual(query["avoid"], ["tolls|ferries"])
        with self.assertRaisesRegex(MobilityError, "travel mode"):
            domain.google_directions("C", travel_mode="teleport")

    def test_google_urls_are_bounded(self):
        domain = MobilityDomain(max_url_chars=180)
        with self.assertRaisesRegex(MobilityError, "URL is too long"):
            domain.google_search("x" * 170)

    def test_osm_search_and_map_handoff_include_attribution(self):
        domain = MobilityDomain()
        search = domain.osm_search("Ohio Union")
        query = parse_qs(urlparse(search["url"]).query)
        self.assertEqual(query["query"], ["Ohio Union"])
        self.assertEqual(search["attribution"], "© OpenStreetMap contributors")
        shown = domain.osm_show(39.998, -83.008, zoom=16)
        self.assertIn("#map=16/39.998/-83.008", shown["url"])
        self.assertEqual(shown["provider"], "openstreetmap")

    def test_coordinates_and_zoom_are_validated(self):
        domain = MobilityDomain()
        with self.assertRaisesRegex(MobilityError, "latitude"):
            domain.osm_show(91, 0)
        with self.assertRaisesRegex(MobilityError, "longitude"):
            domain.osm_show(0, -181)
        with self.assertRaisesRegex(MobilityError, "zoom"):
            domain.osm_show(0, 0, zoom=25)

    def test_cota_profile_is_live_and_gobus_is_schedule_only(self):
        domain = MobilityDomain()
        cota = domain.transit_profile("cota")
        self.assertTrue(cota["realtime"])
        self.assertTrue(cota["feeds"]["static"].endswith("cota.gtfs.zip"))
        self.assertTrue(cota["feeds"]["trip_updates"].endswith("TripUpdates.pb"))
        self.assertTrue(cota["feeds"]["vehicle_positions"].endswith("VehiclePositions.pb"))
        self.assertTrue(cota["feeds"]["alerts"].endswith("Alerts.pb"))
        gobus = domain.transit_profile("gobus")
        self.assertFalse(gobus["realtime"])
        self.assertEqual(gobus["schedule_source"], "transitland:f-utel~uiuc~intercity~bus")
        self.assertNotIn("vehicle_positions", gobus.get("feeds", {}))

    def test_uber_handoff_is_user_confirmed_not_booking_success(self):
        domain = MobilityDomain(uber_client_id="uber-test")
        result = domain.rideshare_handoff(
            "uber",
            destination={
                "latitude": 39.998,
                "longitude": -83.008,
                "nickname": "Ohio Union",
                "address": "1739 N High St, Columbus, OH",
            },
        )
        query = parse_qs(urlparse(result["url"]).query)
        self.assertEqual(query["client_id"], ["uber-test"])
        self.assertEqual(query["pickup"], ["my_location"])
        dropoff = json.loads(query["drop[0]"][0])
        self.assertEqual(dropoff["latitude"], 39.998)
        self.assertEqual(result["status"], "handoff_ready")
        self.assertFalse(result["booking_confirmed"])
        self.assertTrue(result["user_confirmation_required"])

    def test_uber_requires_configuration_instead_of_guessing(self):
        result = MobilityDomain().rideshare_handoff(
            "uber",
            destination={"latitude": 39.998, "longitude": -83.008},
        )
        self.assertEqual(result["status"], "config_required")
        self.assertNotIn("url", result)
        self.assertFalse(result["booking_confirmed"])

    def test_lyft_handoff_is_capability_gated(self):
        missing = MobilityDomain().rideshare_handoff(
            "lyft",
            destination={"latitude": 39.998, "longitude": -83.008},
        )
        self.assertEqual(missing["status"], "config_required")
        domain = MobilityDomain(lyft_client_id="lyft-test")
        result = domain.rideshare_handoff(
            "lyft",
            pickup={"latitude": 39.99, "longitude": -83.01},
            destination={"latitude": 39.998, "longitude": -83.008},
        )
        query = parse_qs(urlparse(result["url"]).query)
        self.assertEqual(query["partner"], ["lyft-test"])
        self.assertEqual(query["pickup[latitude]"], ["39.99"])
        self.assertEqual(query["destination[longitude]"], ["-83.008"])
        self.assertFalse(result["booking_confirmed"])

    def test_rideshare_options_never_invent_estimates(self):
        options = MobilityDomain(uber_client_id="u").rideshare_options()
        by_provider = {item["provider"]: item for item in options}
        self.assertTrue(by_provider["uber"]["handoff_available"])
        self.assertFalse(by_provider["lyft"]["handoff_available"])
        self.assertEqual(by_provider["uber"]["estimates"], "unavailable")
        self.assertEqual(by_provider["lyft"]["estimates"], "unavailable")

    def test_trip_plan_is_read_only_and_uses_last_stop_as_destination(self):
        result = MobilityDomain().trip_plan(
            stops=["A", "B", "C"],
            origin="Home",
            travel_mode="driving",
        )
        query = parse_qs(urlparse(result["handoff"]["url"]).query)
        self.assertEqual(query["origin"], ["Home"])
        self.assertEqual(query["destination"], ["C"])
        self.assertEqual(query["waypoints"], ["A|B"])
        self.assertEqual(result["status"], "plan_ready")
        self.assertFalse(result["side_effect_performed"])

    def test_live_navigation_is_truthfully_unavailable_without_android_bridge(self):
        result = MobilityDomain().navigation_status()
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "android-navigation-bridge-not-connected")


if __name__ == "__main__":
    unittest.main()
