from __future__ import annotations

import json
import unittest
from io import BytesIO
from urllib.error import HTTPError

from zara_calendar.google import GoogleCalendarBackend, GoogleCalendarError


class Response:
    def __init__(self, status, payload=None):
        self.status = status
        self._body = json.dumps(payload if payload is not None else {}).encode()

    def read(self, limit=-1):
        return self._body if limit < 0 else self._body[:limit]

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


class GoogleCalendarBackendTests(unittest.TestCase):
    def test_rejects_unsafe_access_token_before_send(self):
        opener = ScriptedOpener([])
        backend = GoogleCalendarBackend(access_token="bad\nsecret", refresh_token="refresh", client_id="id", client_secret="secret", opener=opener)
        with self.assertRaisesRegex(GoogleCalendarError, "invalid credential"):
            backend.get_event("event-1")
        self.assertEqual(opener.requests, [])

    def test_401_refreshes_once_and_uses_new_token(self):
        first = HTTPError("https://www.googleapis.com/calendar/v3/calendars/primary/events/e1", 401, "unauthorized", {}, BytesIO(b"{}"))
        opener = ScriptedOpener([
            first,
            Response(200, {"access_token": "new-token"}),
            Response(200, {"id": "e1", "summary": "x", "start": {"dateTime": "2026-09-08T10:00:00+00:00"}, "end": {"dateTime": "2026-09-08T11:00:00+00:00"}, "etag": "v2"}),
        ])
        backend = GoogleCalendarBackend(access_token="old-token", refresh_token="refresh", client_id="id", client_secret="secret", opener=opener)
        event = backend.get_event("e1")
        self.assertEqual(event["version"], "v2")
        auth = opener.requests[-1][0].headers["Authorization"]
        self.assertEqual(auth, "Bearer new-token")
        self.assertEqual(len(opener.requests), 3)

    def test_search_follows_page_tokens_and_stops_at_limit(self):
        opener = ScriptedOpener([
            Response(200, {"items": [{"id": "e1", "summary": "one", "start": {"dateTime": "2026-09-08T10:00:00+00:00"}, "end": {"dateTime": "2026-09-08T11:00:00+00:00"}, "etag": "v1"}], "nextPageToken": "next"}),
            Response(200, {"items": [{"id": "e2", "summary": "two", "start": {"dateTime": "2026-09-08T12:00:00+00:00"}, "end": {"dateTime": "2026-09-08T13:00:00+00:00"}, "etag": "v2"}]}),
        ])
        backend = GoogleCalendarBackend(access_token="token", refresh_token="refresh", client_id="id", client_secret="secret", opener=opener)
        events = backend.search_events("2026-09-08T00:00:00+00:00", "2026-09-09T00:00:00+00:00", None, "primary", 2)
        self.assertEqual([event["event_id"] for event in events], ["e1", "e2"])
        self.assertIn("pageToken=next", opener.requests[1][0].full_url)

    def test_cross_origin_absolute_calendar_id_is_data_not_url(self):
        opener = ScriptedOpener([Response(200, {"items": []})])
        backend = GoogleCalendarBackend(access_token="token", refresh_token="refresh", client_id="id", client_secret="secret", opener=opener)
        backend.search_events("2026-09-08T00:00:00+00:00", "2026-09-09T00:00:00+00:00", None, "https://evil.example/x", 1)
        self.assertTrue(opener.requests[0][0].full_url.startswith("https://www.googleapis.com/calendar/v3/calendars/"))
        self.assertNotIn("evil.example/x/events", opener.requests[0][0].full_url)


if __name__ == "__main__":
    unittest.main()
