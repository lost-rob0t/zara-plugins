from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from zara_calendar.google import GoogleCalendarBackend


class Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self, limit=-1):
        return self._body if limit < 0 else self._body[:limit]

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class GoogleTransportCallingConventionTests(unittest.TestCase):
    def test_default_urlopen_receives_timeout_as_keyword_not_request_data(self):
        calls = []

        def fake_urlopen(request, *, timeout):
            calls.append((request, timeout))
            return Response(
                {
                    "id": "e1",
                    "summary": "x",
                    "start": {"dateTime": "2026-09-17T10:00:00+00:00"},
                    "end": {"dateTime": "2026-09-17T11:00:00+00:00"},
                    "etag": "v1",
                }
            )

        with patch("zara_calendar.google.urlopen", fake_urlopen):
            backend = GoogleCalendarBackend(
                access_token="token",
                refresh_token="refresh",
                client_id="id",
                client_secret="secret",
                timeout_seconds=7.5,
            )
            self.assertEqual(backend.get_event("e1")["event_id"], "e1")

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], 7.5)


if __name__ == "__main__":
    unittest.main()
