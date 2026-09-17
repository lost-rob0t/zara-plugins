import io
import json
import sys
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_cota.gtfs import FeedLimits, GTFSFeedError, load_static_gtfs
from zara_cota.plugin import ZaraCotaPlugin


def make_feed(*, malicious_member=None, stop_lat="39.9600"):
    files = {
        "routes.txt": (
            "route_id,route_short_name,route_long_name,route_type,route_color,route_text_color\n"
            "R1,1,High and Broad,3,003366,FFFFFF\n"
            "R2,2,Campus,3,993333,FFFFFF\n"
        ),
        "stops.txt": (
            "stop_id,stop_name,stop_lat,stop_lon\n"
            f"S1,High and Broad,{stop_lat},-83.0000\n"
            "S2,North Market,39.9700,-83.0040\n"
            "S3,Campus,40.0000,-83.0100\n"
        ),
        "trips.txt": (
            "route_id,service_id,trip_id,trip_headsign,direction_id,shape_id\n"
            "R1,WKD,T1,Downtown,0,SH1\n"
            "R1,SAT,T2,Uptown,1,SH2\n"
            "R2,WKD,T3,Campus,0,SH3\n"
        ),
        "stop_times.txt": (
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:00:00,S1,1\n"
            "T1,08:10:00,08:11:00,S2,2\n"
            "T2,09:00:00,09:00:00,S2,1\n"
            "T2,09:10:00,09:10:00,S1,2\n"
            "T3,08:30:00,08:30:00,S1,1\n"
            "T3,08:50:00,08:50:00,S3,2\n"
        ),
        "calendar.txt": (
            "service_id,monday,tuesday,wednesday,thursday,friday,saturday,sunday,start_date,end_date\n"
            "WKD,1,1,1,1,1,0,0,20260101,20261231\n"
            "SAT,0,0,0,0,0,1,0,20260101,20261231\n"
        ),
        "calendar_dates.txt": (
            "service_id,date,exception_type\n"
            "WKD,20260918,2\n"
            "SAT,20260918,1\n"
        ),
        "shapes.txt": (
            "shape_id,shape_pt_lat,shape_pt_lon,shape_pt_sequence\n"
            "SH1,39.9600,-83.0000,1\n"
            "SH1,39.9700,-83.0040,2\n"
            "SH2,39.9700,-83.0040,1\n"
            "SH2,39.9600,-83.0000,2\n"
            "SH3,39.9600,-83.0000,1\n"
            "SH3,40.0000,-83.0100,2\n"
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        if malicious_member is not None:
            archive.writestr(malicious_member, "x")
    return buffer.getvalue()


class StaticGtfsTest(unittest.TestCase):
    def setUp(self):
        self.payload = make_feed()
        self.snapshot = load_static_gtfs(
            self.payload,
            source="fixture",
        )

    def test_loads_routes_stops_trips_shapes_and_stable_generation(self):
        second = load_static_gtfs(self.payload, source="fixture")

        self.assertEqual(len(self.snapshot.routes), 2)
        self.assertEqual(len(self.snapshot.stops), 3)
        self.assertEqual(len(self.snapshot.trips), 3)
        self.assertEqual(self.snapshot.generation, second.generation)
        self.assertEqual(self.snapshot.route("R1")["short_name"], "1")
        self.assertEqual(self.snapshot.stop("S2")["name"], "North Market")
        self.assertEqual(
            self.snapshot.route_geometry("R1", direction_id="0")["coordinates"],
            [[-83.0, 39.96], [-83.004, 39.97]],
        )

    def test_nearby_stops_are_bounded_and_distance_sorted(self):
        rows = self.snapshot.stops_near(39.9601, -83.0001, radius_m=2000, limit=2)

        self.assertEqual([row["stop_id"] for row in rows], ["S1", "S2"])
        self.assertLess(rows[0]["distance_m"], rows[1]["distance_m"])
        with self.assertRaisesRegex(GTFSFeedError, "radius_m"):
            self.snapshot.stops_near(39.96, -83.0, radius_m=0)

    def test_route_stops_follow_trip_sequence_without_duplicates(self):
        rows = self.snapshot.route_stops("R1", direction_id="0")

        self.assertEqual([row["stop_id"] for row in rows], ["S1", "S2"])

    def test_departures_are_scheduled_and_service_calendar_aware(self):
        rows = self.snapshot.departures(
            "S1",
            "2026-09-17",
            after_time="07:55:00",
            limit=10,
        )

        self.assertEqual([row["trip_id"] for row in rows], ["T1", "T3"])
        self.assertTrue(all(row["departure_source"] == "scheduled" for row in rows))
        self.assertTrue(all(row["static_generation"] == self.snapshot.generation for row in rows))

    def test_calendar_exception_removes_weekday_and_adds_saturday_service(self):
        rows = self.snapshot.departures(
            "S1",
            "2026-09-18",
            after_time="00:00:00",
            limit=10,
        )

        self.assertEqual([row["trip_id"] for row in rows], ["T2"])

    def test_rejects_path_traversal_before_extracting(self):
        with self.assertRaisesRegex(GTFSFeedError, "unsafe GTFS member path"):
            load_static_gtfs(
                make_feed(malicious_member="../escape.txt"),
                source="fixture",
            )

    def test_rejects_uncompressed_archive_over_limit(self):
        limits = FeedLimits(
            max_archive_bytes=1024 * 1024,
            max_uncompressed_bytes=64,
            max_member_bytes=1024 * 1024,
            max_members=64,
            max_rows_per_file=100,
            max_field_bytes=1024,
        )
        with self.assertRaisesRegex(GTFSFeedError, "uncompressed size"):
            load_static_gtfs(self.payload, source="fixture", limits=limits)

    def test_rejects_invalid_coordinates(self):
        with self.assertRaisesRegex(GTFSFeedError, "coordinates outside valid range"):
            load_static_gtfs(make_feed(stop_lat="100.0"), source="fixture")

    def test_query_limits_and_unknown_ids_fail_explicitly(self):
        with self.assertRaisesRegex(GTFSFeedError, "unknown route"):
            self.snapshot.route("missing")
        with self.assertRaisesRegex(GTFSFeedError, "limit"):
            self.snapshot.route_list(limit=0)
        with self.assertRaisesRegex(GTFSFeedError, "invalid GTFS time"):
            self.snapshot.departures("S1", "2026-09-17", after_time="nope")


class FakeFetcher:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def fetch(self, url):
        self.calls.append(url)
        return self.payload


class PluginTest(unittest.TestCase):
    def test_refresh_is_explicit_and_nearby_query_uses_supplied_coordinates(self):
        fetcher = FakeFetcher(make_feed())
        plugin = ZaraCotaPlugin(fetcher=fetcher)

        before = json.loads(plugin.status())
        self.assertEqual(before["static_feed"], "not_loaded")
        self.assertEqual(fetcher.calls, [])

        refreshed = json.loads(plugin.refresh_static())
        nearby = json.loads(plugin.stops_near(39.9601, -83.0001, radius_m=500, limit=5))
        departures = json.loads(plugin.departures("S1", "2026-09-17", "07:55:00", 5))

        self.assertEqual(refreshed["status"], "refreshed")
        self.assertEqual(fetcher.calls, ["https://www.cota.com/data/cota.gtfs.zip"])
        self.assertEqual(nearby["stops"][0]["stop_id"], "S1")
        self.assertFalse(departures["realtime_applied"])
        self.assertEqual(departures["status"], "ready_scheduled")

    def test_failed_refresh_does_not_replace_last_good_snapshot(self):
        class ToggleFetcher:
            def __init__(self):
                self.good = True

            def fetch(self, url):
                if self.good:
                    return make_feed()
                return b"not a zip"

        fetcher = ToggleFetcher()
        plugin = ZaraCotaPlugin(fetcher=fetcher)
        first = json.loads(plugin.refresh_static())
        fetcher.good = False

        with self.assertRaises(GTFSFeedError):
            plugin.refresh_static()

        after = json.loads(plugin.status())
        self.assertEqual(after["static_generation"], first["static_generation"])
        self.assertEqual(after["status"], "ready_static")


if __name__ == "__main__":
    unittest.main()
