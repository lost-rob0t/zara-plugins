from __future__ import annotations

import json
import socket
import unittest
from io import BytesIO
from urllib.error import HTTPError, URLError

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


def http_error(code, payload=None):
    body = json.dumps(payload if payload is not None else {}).encode()
    return HTTPError("https://www.googleapis.com/calendar/v3/test", code, "provider error", {}, BytesIO(body))


def event_payload(event_id="e1", version="v1"):
    return {
        "id": event_id,
        "summary": "x",
        "start": {"dateTime": "2026-09-08T10:00:00+00:00"},
        "end": {"dateTime": "2026-09-08T11:00:00+00:00"},
        "etag": version,
    }


class GoogleCalendarBackendTests(unittest.TestCase):
    def make_backend(self, opener, *, sleeper=lambda _: None, **kwargs):
        return GoogleCalendarBackend(
            access_token="token",
            refresh_token="refresh",
            client_id="id",
            client_secret="secret",
            opener=opener,
            sleeper=sleeper,
            **kwargs,
        )

    def test_rejects_unsafe_access_token_before_send(self):
        opener = ScriptedOpener([])
        backend = GoogleCalendarBackend(
            access_token="bad\nsecret",
            refresh_token="refresh",
            client_id="id",
            client_secret="secret",
            opener=opener,
        )
        with self.assertRaisesRegex(GoogleCalendarError, "invalid credential"):
            backend.get_event("event-1")
        self.assertEqual(opener.requests, [])

    def test_401_refreshes_once_and_uses_new_token(self):
        first = http_error(401)
        opener = ScriptedOpener([
            first,
            Response(200, {"access_token": "new-token"}),
            Response(200, event_payload(version="v2")),
        ])
        backend = GoogleCalendarBackend(
            access_token="old-token",
            refresh_token="refresh",
            client_id="id",
            client_secret="secret",
            opener=opener,
        )
        event = backend.get_event("e1")
        self.assertEqual(event["version"], "v2")
        auth = opener.requests[-1][0].headers["Authorization"]
        self.assertEqual(auth, "Bearer new-token")
        self.assertEqual(len(opener.requests), 3)

    def test_revoked_refresh_token_fails_reauth_without_second_retry(self):
        opener = ScriptedOpener([
            http_error(401),
            HTTPError(
                "https://oauth2.googleapis.com/token",
                400,
                "invalid_grant",
                {},
                BytesIO(b'{"error":"invalid_grant"}'),
            ),
        ])
        backend = self.make_backend(opener)
        with self.assertRaisesRegex(GoogleCalendarError, "reauth-required"):
            backend.get_event("e1")
        self.assertEqual(len(opener.requests), 2)

    def test_search_follows_page_tokens_and_stops_at_limit(self):
        opener = ScriptedOpener([
            Response(200, {"items": [event_payload("e1", "v1")], "nextPageToken": "next"}),
            Response(200, {"items": [event_payload("e2", "v2")]}),
        ])
        backend = self.make_backend(opener)
        events = backend.search_events(
            "2026-09-08T00:00:00+00:00",
            "2026-09-09T00:00:00+00:00",
            None,
            "primary",
            2,
        )
        self.assertEqual([event["event_id"] for event in events], ["e1", "e2"])
        self.assertIn("pageToken=next", opener.requests[1][0].full_url)

    def test_cross_origin_absolute_calendar_id_is_data_not_url(self):
        opener = ScriptedOpener([Response(200, {"items": []})])
        backend = self.make_backend(opener)
        backend.search_events(
            "2026-09-08T00:00:00+00:00",
            "2026-09-09T00:00:00+00:00",
            None,
            "https://evil.example/x",
            1,
        )
        self.assertTrue(opener.requests[0][0].full_url.startswith("https://www.googleapis.com/calendar/v3/calendars/"))
        self.assertNotIn("evil.example/x/events", opener.requests[0][0].full_url)

    def test_get_retries_429_and_5xx_with_bounded_exponential_backoff(self):
        delays = []
        opener = ScriptedOpener([
            http_error(429),
            http_error(500),
            Response(200, event_payload()),
        ])
        backend = self.make_backend(opener, sleeper=delays.append)
        event = backend.get_event("e1")
        self.assertEqual(event["event_id"], "e1")
        self.assertEqual(delays, [0.25, 0.5])
        self.assertEqual(len(opener.requests), 3)

    def test_rate_limit_403_retries_but_permission_403_does_not(self):
        rate_payload = {
            "error": {
                "errors": [{"reason": "rateLimitExceeded"}],
                "code": 403,
            }
        }
        delays = []
        retrying = ScriptedOpener([
            http_error(403, rate_payload),
            Response(200, event_payload()),
        ])
        backend = self.make_backend(retrying, sleeper=delays.append)
        self.assertEqual(backend.get_event("e1")["event_id"], "e1")
        self.assertEqual(delays, [0.25])

        denied = ScriptedOpener([http_error(403, {"error": {"errors": [{"reason": "forbiddenForNonOrganizer"}]}})])
        backend = self.make_backend(denied)
        with self.assertRaisesRegex(GoogleCalendarError, "provider-http-403"):
            backend.get_event("e1")
        self.assertEqual(len(denied.requests), 1)

    def test_permanent_400_is_not_retried(self):
        opener = ScriptedOpener([http_error(400)])
        backend = self.make_backend(opener)
        with self.assertRaisesRegex(GoogleCalendarError, "provider-http-400"):
            backend.get_event("e1")
        self.assertEqual(len(opener.requests), 1)

    def test_read_timeout_retries_then_fails_provider_unavailable(self):
        delays = []
        opener = ScriptedOpener([
            socket.timeout("slow"),
            URLError("still unavailable"),
            socket.timeout("still slow"),
        ])
        backend = self.make_backend(opener, sleeper=delays.append)
        with self.assertRaisesRegex(GoogleCalendarError, "provider-unavailable"):
            backend.get_event("e1")
        self.assertEqual(delays, [0.25, 0.5])
        self.assertEqual(len(opener.requests), 3)

    def test_ambiguous_mutation_5xx_is_not_retried(self):
        opener = ScriptedOpener([http_error(500)])
        backend = self.make_backend(opener)
        event = {
            "calendar_id": "primary",
            "title": "x",
            "start": "2026-09-08T10:00:00+00:00",
            "end": "2026-09-08T11:00:00+00:00",
            "timezone": "UTC",
            "attendees": [],
            "recurrence": None,
            "reminders": [],
        }
        with self.assertRaisesRegex(GoogleCalendarError, "mutation-outcome-unknown"):
            backend.create_event(event)
        self.assertEqual(len(opener.requests), 1)

    def test_rate_limited_mutation_is_retried_because_provider_rejected_it(self):
        delays = []
        opener = ScriptedOpener([
            http_error(429),
            Response(200, event_payload()),
        ])
        backend = self.make_backend(opener, sleeper=delays.append)
        evidence = backend.create_event({
            "calendar_id": "primary",
            "title": "x",
            "start": "2026-09-08T10:00:00+00:00",
            "end": "2026-09-08T11:00:00+00:00",
            "timezone": "UTC",
            "attendees": [],
            "recurrence": None,
            "reminders": [],
        })
        self.assertTrue(evidence["accepted"])
        self.assertEqual(delays, [0.25])

    def test_two_backends_do_not_cross_credentials(self):
        first = ScriptedOpener([Response(200, event_payload("a"))])
        second = ScriptedOpener([Response(200, event_payload("b"))])
        a = GoogleCalendarBackend(access_token="token-a", refresh_token="refresh-a", client_id="id-a", client_secret="secret-a", opener=first)
        b = GoogleCalendarBackend(access_token="token-b", refresh_token="refresh-b", client_id="id-b", client_secret="secret-b", opener=second)
        a.get_event("a")
        b.get_event("b")
        self.assertEqual(first.requests[0][0].headers["Authorization"], "Bearer token-a")
        self.assertEqual(second.requests[0][0].headers["Authorization"], "Bearer token-b")

    def test_free_busy_rejects_malformed_provider_shape(self):
        opener = ScriptedOpener([Response(200, {"calendars": {"primary": {"busy": [{"start": "x"}]}}})])
        backend = self.make_backend(opener)
        with self.assertRaisesRegex(GoogleCalendarError, "malformed free/busy"):
            backend.free_busy("2026-09-08T00:00:00+00:00", "2026-09-09T00:00:00+00:00", ["primary"])


if __name__ == "__main__":
    unittest.main()
