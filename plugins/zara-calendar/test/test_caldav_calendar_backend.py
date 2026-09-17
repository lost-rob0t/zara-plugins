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
    escaped = (
        calendar_data.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
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

    def test_requires_https_calendar_collection(self):
        with self.assertRaisesRegex(CalDavCalendarError, "https"):
            CalDavCalendarBackend(
                calendar_url="http://calendar.example.test/work/",
                username="me",
                password="secret",
            )

    def test_rejects_ambiguous_or_unsafe_credentials_before_send(self):
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
        self.assertEqual(opener.requests, [])

    def test_report_uses_basic_auth_depth_one_time_range_and_expand(self):
        opener = ScriptedOpener([Response(multistatus(ical()), url=CALENDAR_URL)])
        backend = self.make_backend(opener)

        events = backend.search_events(
            "2026-09-17T00:00:00+00:00",
            "2026-09-18T00:00:00+00:00",
            None,
            "work",
            10,
        )

        self.assertEqual(events[0]["event_id"], "e1.ics")
        request = opener.requests[0][0]
        self.assertEqual(request.get_method(), "REPORT")
        self.assertEqual(request.get_header("Depth"), "1")
        auth = request.get_header("Authorization")
        self.assertEqual(auth, "Basic " + base64.b64encode(b"me:secret").decode("ascii"))
        body = request.data.decode()
        self.assertIn("calendar-query", body)
        self.assertIn("getetag", body)
        self.assertIn("calendar-data", body)
        self.assertIn("expand", body)
        self.assertIn("20260917T000000Z", body)
        self.assertIn("20260918T000000Z", body)

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

    def test_caller_calendar_id_cannot_select_another_collection_or_origin(self):
        opener = ScriptedOpener([])
        backend = self.make_backend(opener)
        with self.assertRaisesRegex(CalDavCalendarError, "configured calendar"):
            backend.search_events(
                "2026-09-17T00:00:00+00:00",
                "2026-09-18T00:00:00+00:00",
                None,
                "https://evil.example/calendar",
                1,
            )
        self.assertEqual(opener.requests, [])

    def test_multistatus_parses_folded_text_timezone_attendees_rrule_and_alarm(self):
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
        backend = self.make_backend(opener)
        event = backend.search_events(
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

    def test_text_search_is_expressed_as_summary_filter(self):
        opener = ScriptedOpener([Response(multistatus(ical(title="Roadmap")), url=CALENDAR_URL)])
        backend = self.make_backend(opener)
        backend.search_events(
            "2026-09-17T00:00:00+00:00",
            "2026-09-18T00:00:00+00:00",
            "Roadmap & review",
            "work",
            2,
        )
        body = opener.requests[0][0].data.decode()
        self.assertIn("prop-filter", body)
        self.assertIn("SUMMARY", body)
        self.assertIn("Roadmap &amp; review", body)

    def test_get_rejects_event_id_origin_and_path_injection_before_send(self):
        opener = ScriptedOpener([])
        backend = self.make_backend(opener)
        for event_id in ("https://evil.example/e.ics", "../e.ics", "a/b.ics"):
            with self.subTest(event_id=event_id):
                with self.assertRaisesRegex(CalDavCalendarError, "event id"):
                    backend.get_event(event_id)
        self.assertEqual(opener.requests, [])

    def test_get_uses_response_etag_as_version(self):
        opener = ScriptedOpener([
            Response(
                ical(uid="uid-existing").encode(),
                headers={"ETag": '"etag-7"'},
                url=CALENDAR_URL + "e1.ics",
            )
        ])
        backend = self.make_backend(opener)
        event = backend.get_event("e1.ics")
        self.assertEqual(event["version"], '"etag-7"')
        self.assertEqual(event["event_id"], "e1.ics")
        self.assertEqual(opener.requests[0][0].get_method(), "GET")

    def test_get_404_is_absent_and_cross_origin_response_is_rejected(self):
        absent = self.make_backend(ScriptedOpener([http_error(404)]))
        self.assertIsNone(absent.get_event("e1.ics"))

        opener = ScriptedOpener([
            Response(
                ical().encode(),
                headers={"ETag": '"v1"'},
                url="https://evil.example/e1.ics",
            )
        ])
        backend = self.make_backend(opener)
        with self.assertRaisesRegex(CalDavCalendarError, "origin"):
            backend.get_event("e1.ics")

    def test_create_uses_conditional_put_and_returns_strong_etag_evidence(self):
        opener = ScriptedOpener([
            Response(b"", headers={"ETag": '"created-v1"'}, url=CALENDAR_URL + "zara-generated-uid.ics")
        ])
        backend = self.make_backend(opener)
        evidence = backend.create_event(
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
        self.assertIn("UID:generated-uid", body)
        self.assertIn("DTSTART;TZID=America/New_York:20260917T090000", body)
        self.assertIn("ATTENDEE:mailto:alice@example.com", body)
        self.assertIn("RRULE:FREQ=WEEKLY;COUNT=2", body)
        self.assertIn("TRIGGER:-PT15M", body)
        self.assertEqual(
            evidence,
            {"accepted": True, "event_id": "zara-generated-uid.ics", "version": '"created-v1"'},
        )

    def test_update_preserves_existing_uid_and_uses_if_match(self):
        opener = ScriptedOpener([
            Response(
                ical(uid="server-owned-uid").encode(),
                headers={"ETag": '"v1"'},
                url=CALENDAR_URL + "e1.ics",
            ),
            Response(b"", headers={"ETag": '"v2"'}, url=CALENDAR_URL + "e1.ics"),
        ])
        backend = self.make_backend(opener)
        evidence = backend.update_event("e1.ics", '"v1"', {"title": "Updated"})
        put = opener.requests[1][0]
        self.assertEqual(put.get_method(), "PUT")
        self.assertEqual(put.get_header("If-match"), '"v1"')
        self.assertIn("UID:server-owned-uid", put.data.decode())
        self.assertIn("SUMMARY:Updated", put.data.decode())
        self.assertEqual(evidence["version"], '"v2"')

    def test_update_and_delete_map_conflicts_to_stale_version(self):
        update_opener = ScriptedOpener([
            Response(
                ical().encode(),
                headers={"ETag": '"v1"'},
                url=CALENDAR_URL + "e1.ics",
            ),
            http_error(412),
        ])
        backend = self.make_backend(update_opener)
        with self.assertRaisesRegex(CalDavCalendarError, "stale-version"):
            backend.update_event("e1.ics", '"old"', {"title": "Updated"})

        delete_opener = ScriptedOpener([http_error(409)])
        backend = self.make_backend(delete_opener)
        with self.assertRaisesRegex(CalDavCalendarError, "stale-version"):
            backend.delete_event("e1.ics", '"old"')

    def test_delete_uses_if_match(self):
        opener = ScriptedOpener([Response(b"", url=CALENDAR_URL + "e1.ics")])
        backend = self.make_backend(opener)
        evidence = backend.delete_event("e1.ics", '"v1"')
        request = opener.requests[0][0]
        self.assertEqual(request.get_method(), "DELETE")
        self.assertEqual(request.get_header("If-match"), '"v1"')
        self.assertEqual(evidence["accepted"], True)

    def test_free_busy_excludes_transparent_events(self):
        opaque = ical(uid="opaque", title="Busy")
        transparent = ical(
            uid="free",
            title="FYI",
            start="20260917T150000Z",
            end="20260917T160000Z",
            extra="TRANSP:TRANSPARENT\r\n",
        )
        body = (
            multistatus(opaque, href="/dav/calendars/me/work/opaque.ics", etag='"o"')
            .decode()
            .replace("</D:multistatus>", "")
            + multistatus(transparent, href="/dav/calendars/me/work/free.ics", etag='"f"')
            .decode()
            .replace('<?xml version="1.0" encoding="utf-8"?><D:multistatus xmlns:D="DAV:" xmlns:C="urn:ietf:params:xml:ns:caldav">', "")
        ).encode()
        opener = ScriptedOpener([Response(body, url=CALENDAR_URL)])
        backend = self.make_backend(opener)
        intervals = backend.free_busy(
            "2026-09-17T00:00:00+00:00",
            "2026-09-18T00:00:00+00:00",
            ["work"],
        )
        self.assertEqual(len(intervals), 1)
        self.assertEqual(intervals[0]["event_id"], "opaque.ics")

    def test_malformed_xml_oversized_response_and_transport_failure_fail_closed(self):
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
            ScriptedOpener([Response(b"x" * 33, url=CALENDAR_URL)]),
            max_response_bytes=32,
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
