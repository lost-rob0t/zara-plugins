from __future__ import annotations

import base64
import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError

from zara_calendar.caldav import CalDavCalendarBackend, CalDavCalendarError


CALENDAR_URL = "https://calendar.example.test/dav/calendars/me/work/"


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
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def http_error(code, body=b""):
    return HTTPError(CALENDAR_URL, code, "provider error", {}, BytesIO(body))


def ical(
    *,
    uid="uid-1",
    title="Planning",
    start="20260917T130000Z",
    end="20260917T140000Z",
    extra="",
):
    return (
        "BEGIN:VCALENDAR\r\n"
        "VERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"DTSTART:{start}\r\n"
        f"DTEND:{end}\r\n"
        f"SUMMARY:{title}\r\n"
        f"{extra}"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )


def multistatus(calendar_data, *, href="/dav/calendars/me/work/e1.ics", etag='"v1"'):
    escaped = calendar_data.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">'
        "<D:response>"
        f"<D:href>{href}</D:href>"
        "<D:propstat><D:prop>"
        f"<D:getetag>{etag}</D:getetag>"
        f"<C:calendar-data>{escaped}</C:calendar-data>"
        "</D:prop><D:status>HTTP/1.1 200 OK</D:status></D:propstat>"
        "</D:response>"
        "</D:multistatus>"
    ).encode()


class CalDavCalendarBackendTests(unittest.TestCase):
    def make_backend(self, opener, **kwargs):
        return CalDavCalendarBackend(
            calendar_url=CALENDAR_URL,
            calendar_id="work",
            username="me",
            password="secret",
            opener=opener,
            uid_factory=lambda: "generated-uid",
            **kwargs,
        )

    def test_https_auth_and_calendar_origin_are_closed(self):
        with self.assertRaisesRegex(CalDavCalendarError, "https"):
            CalDavCalendarBackend(
                calendar_url="http://calendar.example.test/work/",
                username="me",
                password="secret",
            )

        opener = ScriptedOpener([])
        with self.assertRaisesRegex(CalDavCalendarError, "auth"):
            CalDavCalendarBackend(
                calendar_url=CALENDAR_URL,
                username="me",
                password="secret",
                bearer_token="token",
                opener=opener,
            )
        with self.assertRaisesRegex(CalDavCalendarError, "credential"):
            CalDavCalendarBackend(
                calendar_url=CALENDAR_URL,
                username="bad\nname",
                password="secret",
                opener=opener,
            )

        backend = self.make_backend(opener)
        with self.assertRaisesRegex(CalDavCalendarError, "configured calendar"):
            backend.search_events(
                "2026-09-17T00:00:00+00:00",
                "2026-09-18T00:00:00+00:00",
                None,
                "https://evil.example/calendar",
                1,
            )
        for event_id in ("https://evil.example/e.ics", "../e.ics", "a/b.ics"):
            with self.subTest(event_id=event_id):
                with self.assertRaisesRegex(CalDavCalendarError, "event id"):
                    backend.get_event(event_id)
        self.assertEqual(opener.requests, [])

    def test_report_uses_depth_auth_time_range_expand_and_summary_filter(self):
        opener = ScriptedOpener([Response(multistatus(ical(title="Roadmap")), url=CALENDAR_URL)])
        backend = self.make_backend(opener)
        events = backend.search_events(
            "2026-09-17T00:00:00+00:00",
            "2026-09-18T00:00:00+00:00",
            "Roadmap & review",
            "work",
            10,
        )
        self.assertEqual(events[0]["event_id"], "e1.ics")

        request = opener.requests[0][0]
        self.assertEqual(request.get_method(), "REPORT")
        self.assertEqual(request.get_header("Depth"), "1")
        self.assertEqual(
            request.get_header("Authorization"),
            "Basic " + base64.b64encode(b"me:secret").decode("ascii"),
        )
        body = request.data.decode()
        for expected in (
            "calendar-query",
            "getetag",
            "calendar-data",
            "expand",
            "20260917T000000Z",
            "20260918T000000Z",
            "prop-filter",
            "SUMMARY",
            "Roadmap &amp; review",
        ):
            self.assertIn(expected, body)

    def test_bearer_mode_never_uses_basic_credentials(self):
        opener = ScriptedOpener([Response(multistatus(ical()), url=CALENDAR_URL)])
        backend = CalDavCalendarBackend(
            calendar_url=CALENDAR_URL,
            calendar_id="work",
            bearer_token="bearer-value",
            opener=opener,
        )
        backend.search_events(
            "2026-09-17T00:00:00+00:00",
            "2026-09-18T00:00:00+00:00",
            None,
            "work",
            1,
        )
        self.assertEqual(opener.requests[0][0].get_header("Authorization"), "Bearer bearer-value")

    def test_multistatus_normalizes_timezone_folded_text_attendee_rrule_and_alarm(self):
        data = (
            "BEGIN:VCALENDAR\r\n"
            "VERSION:2.0\r\n"
            "BEGIN:VEVENT\r\n"
            "UID:uid-2\r\n"
            "DTSTART;TZID=America/New_York:20260917T090000\r\n"
            "DTEND;TZID=America/New_York:20260917T100000\r\n"
            "SUMMARY:Planning\\, deep\r\n"
            " dive\r\n"
            "ATTENDEE;CN=Alice:mailto:alice@example.com\r\n"
            "RRULE:FREQ=WEEKLY;COUNT=2\r\n"
            "BEGIN:VALARM\r\n"
            "ACTION:DISPLAY\r\n"
            "TRIGGER:-PT15M\r\n"
            "END:VALARM\r\n"
            "END:VEVENT\r\n"
            "END:VCALENDAR\r\n"
        )
        opener = ScriptedOpener([Response(multistatus(data, etag='"v9"'), url=CALENDAR_URL)])
        event = self.make_backend(opener).search_events(
            "2026-09-17T00:00:00-04:00",
            "2026-09-18T00:00:00-04:00",
            None,
            "work",
            1,
        )[0]
        self.assertEqual(event["title"], "Planning, deepdive")
        self.assertEqual(event["timezone"], "America/New_York")
        self.assertEqual(event["start"], "2026-09-17T09:00:00-04:00")
        self.assertEqual(event["end"], "2026-09-17T10:00:00-04:00")
        self.assertEqual(event["attendees"], ["alice@example.com"])
        self.assertEqual(event["recurrence"], {"rrule": "RRULE:FREQ=WEEKLY;COUNT=2"})
        self.assertEqual(event["reminders"], [{"minutes_before": 15}])
        self.assertEqual(event["version"], '"v9"')

    def test_get_uses_strong_etag_and_404_is_absent(self):
        opener = ScriptedOpener([
            Response(
                ical(uid="uid-existing").encode(),
                headers={"ETag": '"etag-7"'},
                url=CALENDAR_URL + "e1.ics",
            )
        ])
        event = self.make_backend(opener).get_event("e1.ics")
        self.assertEqual(event["version"], '"etag-7"')
        self.assertEqual(event["event_id"], "e1.ics")

        absent = self.make_backend(ScriptedOpener([http_error(404)]))
        self.assertIsNone(absent.get_event("e1.ics"))

    def test_cross_origin_response_is_rejected(self):
        opener = ScriptedOpener([
            Response(
                ical().encode(),
                headers={"ETag": '"v1"'},
                url="https://evil.example/e1.ics",
            )
        ])
        with self.assertRaisesRegex(CalDavCalendarError, "origin"):
            self.make_backend(opener).get_event("e1.ics")

    def test_create_is_conditional_and_returns_etag_evidence(self):
        opener = ScriptedOpener([
            Response(
                b"",
                headers={"ETag": '"created-v1"'},
                url=CALENDAR_URL + "zara-generated-uid.ics",
            )
        ])
        evidence = self.make_backend(opener).create_event(
            {
                "calendar_id": "work",
                "title": "Planning",
                "start": "2026-09-17T09:00:00-04:00",
                "end": "2026-09-17T10:00:00-04:00",
                "timezone": "America/New_York",
                "attendees": ["alice@example.com"],
                "recurrence": {"rrule": "RRULE:FREQ=WEEKLY;COUNT=2"},
                "reminders": [{"minutes_before": 15}],
            }
        )
        request = opener.requests[0][0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(request.get_header("If-none-match"), "*")
        self.assertEqual(request.get_header("Content-type"), "text/calendar; charset=utf-8")
        body = request.data.decode()
        for expected in (
            "UID:generated-uid",
            "DTSTART;TZID=America/New_York:20260917T090000",
            "ATTENDEE:mailto:alice@example.com",
            "RRULE:FREQ=WEEKLY;COUNT=2",
            "TRIGGER:-PT15M",
        ):
            self.assertIn(expected, body)
        self.assertEqual(
            evidence,
            {"accepted": True, "event_id": "zara-generated-uid.ics", "version": '"created-v1"'},
        )

    def test_update_preserves_uid_uses_if_match_and_maps_stale_version(self):
        opener = ScriptedOpener([
            Response(
                ical(uid="server-owned-uid").encode(),
                headers={"ETag": '"v1"'},
                url=CALENDAR_URL + "e1.ics",
            ),
            Response(b"", headers={"ETag": '"v2"'}, url=CALENDAR_URL + "e1.ics"),
        ])
        evidence = self.make_backend(opener).update_event("e1.ics", '"v1"', {"title": "Updated"})
        put = opener.requests[1][0]
        self.assertEqual(put.get_method(), "PUT")
        self.assertEqual(put.get_header("If-match"), '"v1"')
        self.assertIn("UID:server-owned-uid", put.data.decode())
        self.assertIn("SUMMARY:Updated", put.data.decode())
        self.assertEqual(evidence["version"], '"v2"')

        stale = ScriptedOpener([
            Response(ical().encode(), headers={"ETag": '"v1"'}, url=CALENDAR_URL + "e1.ics"),
            http_error(412),
        ])
        with self.assertRaisesRegex(CalDavCalendarError, "stale-version"):
            self.make_backend(stale).update_event("e1.ics", '"old"', {"title": "Updated"})

    def test_delete_uses_if_match_and_maps_conflicts(self):
        opener = ScriptedOpener([Response(b"", url=CALENDAR_URL + "e1.ics")])
        evidence = self.make_backend(opener).delete_event("e1.ics", '"v1"')
        request = opener.requests[0][0]
        self.assertEqual(request.get_method(), "DELETE")
        self.assertEqual(request.get_header("If-match"), '"v1"')
        self.assertTrue(evidence["accepted"])

        stale = self.make_backend(ScriptedOpener([http_error(409)]))
        with self.assertRaisesRegex(CalDavCalendarError, "stale-version"):
            stale.delete_event("e1.ics", '"old"')

    def test_free_busy_excludes_transparent_events(self):
        opaque = multistatus(
            ical(uid="opaque", title="Busy"),
            href="/dav/calendars/me/work/opaque.ics",
            etag='"o"',
        ).decode().replace("</D:multistatus>", "")
        transparent = multistatus(
            ical(
                uid="free",
                title="FYI",
                start="20260917T150000Z",
                end="20260917T160000Z",
                extra="TRANSP:TRANSPARENT\r\n",
            ),
            href="/dav/calendars/me/work/free.ics",
            etag='"f"',
        ).decode().replace(
            '<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">',
            "",
        )
        opener = ScriptedOpener([Response((opaque + transparent).encode(), url=CALENDAR_URL)])
        intervals = self.make_backend(opener).free_busy(
            "2026-09-17T00:00:00+00:00",
            "2026-09-18T00:00:00+00:00",
            ["work"],
        )
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals[0]["event_id"], "opaque.ics")

    def test_malformed_oversized_and_transport_failures_fail_closed(self):
        malformed = self.make_backend(ScriptedOpener([Response(b"not xml", url=CALENDAR_URL)]))
        with self.assertRaisesRegex(CalDavCalendarError, "XML"):
            malformed.search_events(
                "2026-09-17T00:00:00+00:00",
                "2026-09-18T00:00:00+00:00",
                None,
                "work",
                1,
            )

        oversized = self.make_backend(
            ScriptedOpener([Response(b"x" * 1025, url=CALENDAR_URL)]),
            max_response_bytes=1024,
        )
        with self.assertRaisesRegex(CalDavCalendarError, "too large"):
            oversized.search_events(
                "2026-09-17T00:00:00+00:00",
                "2026-09-18T00:00:00+00:00",
                None,
                "work",
                1,
            )

        unavailable = self.make_backend(ScriptedOpener([URLError("offline")]))
        with self.assertRaisesRegex(CalDavCalendarError, "unavailable"):
            unavailable.get_event("e1.ics")


if __name__ == "__main__":
    unittest.main()
