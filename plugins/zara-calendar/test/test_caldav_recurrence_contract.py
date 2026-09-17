from __future__ import annotations

import sys
import unittest
from pathlib import Path

LIB_ROOT = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB_ROOT))

from zara_calendar.caldav import CalDavCalendarBackend, CalDavCalendarError


CALENDAR_URL = "https://calendar.example.test/dav/calendars/me/work/"
RESOURCE_URL = CALENDAR_URL + "series.ics"


class Response:
    def __init__(self, body=b"", *, headers=None, url=CALENDAR_URL):
        self._body = body
        self.headers = headers or {}
        self._url = url

    def read(self, limit=-1):
        return self._body if limit < 0 else self._body[:limit]

    def geturl(self):
        return self._url

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class ScriptedOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return self.responses.pop(0)


def recurrence_resource():
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:series-1\r\n"
        "DTSTART:20260917T130000Z\r\n"
        "DTEND:20260917T140000Z\r\n"
        "SUMMARY:Weekly planning\r\n"
        "RRULE:FREQ=WEEKLY;COUNT=2\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:series-1\r\n"
        "RECURRENCE-ID:20260924T130000Z\r\n"
        "DTSTART:20260924T150000Z\r\n"
        "DTEND:20260924T160000Z\r\n"
        "SUMMARY:Weekly planning moved\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def expanded_resource():
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:series-1\r\n"
        "DTSTART:20260917T130000Z\r\n"
        "DTEND:20260917T140000Z\r\n"
        "SUMMARY:Weekly planning\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:series-1\r\n"
        "RECURRENCE-ID:20260924T130000Z\r\n"
        "DTSTART:20260924T150000Z\r\n"
        "DTEND:20260924T160000Z\r\n"
        "SUMMARY:Weekly planning moved\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def multistatus(calendar_data):
    escaped = calendar_data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        "<D:response>"
        "<D:href>/dav/calendars/me/work/series.ics</D:href>"
        "<D:propstat><D:prop>"
        '<D:getetag>"v1"</D:getetag>'
        f"<C:calendar-data>{escaped}</C:calendar-data>"
        "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
        "</D:response>"
        "</D:multistatus>"
    ).encode()


class CalDavRecurrenceContractTests(unittest.TestCase):
    @staticmethod
    def make_backend(opener):
        return CalDavCalendarBackend(
            calendar_url=CALENDAR_URL,
            calendar_id="work",
            username="me",
            password="secret",
            opener=opener,
        )

    def test_expanded_report_surfaces_every_vevent_for_search_and_free_busy(self):
        payload = multistatus(expanded_resource())
        search = self.make_backend(ScriptedOpener([Response(payload, url=CALENDAR_URL)]))
        events = search.search_events(
            "2026-09-17T00:00:00+00:00",
            "2026-09-25T00:00:00+00:00",
            None,
            "work",
            10,
        )
        self.assertEqual(len(events), 2)
        self.assertEqual([event["event_id"] for event in events], ["series.ics", "series.ics"])
        self.assertEqual(
            [event["start"] for event in events],
            ["2026-09-17T13:00:00+00:00", "2026-09-24T15:00:00+00:00"],
        )

        busy = self.make_backend(ScriptedOpener([Response(payload, url=CALENDAR_URL)]))
        intervals = busy.free_busy(
            "2026-09-17T00:00:00+00:00",
            "2026-09-25T00:00:00+00:00",
            ["work"],
        )
        self.assertEqual(len(intervals), 2)
        self.assertEqual(
            [interval["start"] for interval in intervals],
            ["2026-09-17T13:00:00+00:00", "2026-09-24T15:00:00+00:00"],
        )

    def test_multi_vevent_update_fails_closed_before_put(self):
        opener = ScriptedOpener(
            [
                Response(recurrence_resource().encode(), headers={"ETag": '"v1"'}, url=RESOURCE_URL),
                Response(b"", headers={"ETag": '"v2"'}, url=RESOURCE_URL),
            ]
        )
        backend = self.make_backend(opener)

        with self.assertRaisesRegex(CalDavCalendarError, "multi-component recurring"):
            backend.update_event("series.ics", '"v1"', {"title": "Updated"})

        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(opener.requests[0][0].get_method(), "GET")


if __name__ == "__main__":
    unittest.main()
