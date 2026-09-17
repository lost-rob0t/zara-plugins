from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from zara_calendar.caldav import CalDavCalendarBackend
from zara_calendar.domain import CalendarError
from zara_calendar.google import GoogleCalendarBackend
from zara_calendar.plugin import _backend_from_environment


class CalendarProviderSelectionTests(unittest.TestCase):
    def test_empty_environment_has_no_backend(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(_backend_from_environment())

    def test_google_environment_preserves_existing_backend(self):
        env = {
            "ZARA_CALENDAR_GOOGLE_ACCESS_TOKEN": "access",
            "ZARA_CALENDAR_GOOGLE_REFRESH_TOKEN": "refresh",
            "ZARA_CALENDAR_GOOGLE_CLIENT_ID": "client",
            "ZARA_CALENDAR_GOOGLE_CLIENT_SECRET": "secret",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertIsInstance(_backend_from_environment(), GoogleCalendarBackend)

    def test_caldav_basic_environment_selects_caldav(self):
        env = {
            "ZARA_CALENDAR_CALDAV_URL": "https://calendar.example.test/dav/work/",
            "ZARA_CALENDAR_CALDAV_CALENDAR_ID": "work",
            "ZARA_CALENDAR_CALDAV_USERNAME": "me",
            "ZARA_CALENDAR_CALDAV_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=True):
            backend = _backend_from_environment()
        self.assertIsInstance(backend, CalDavCalendarBackend)
        self.assertEqual(backend.default_calendar_id, "work")

    def test_caldav_bearer_environment_selects_caldav(self):
        env = {
            "ZARA_CALENDAR_BACKEND": "caldav",
            "ZARA_CALENDAR_CALDAV_URL": "https://calendar.example.test/dav/work/",
            "ZARA_CALENDAR_CALDAV_BEARER_TOKEN": "token",
        }
        with patch.dict(os.environ, env, clear=True):
            self.assertIsInstance(_backend_from_environment(), CalDavCalendarBackend)

    def test_ambiguous_provider_configuration_requires_explicit_selection(self):
        env = {
            "ZARA_CALENDAR_GOOGLE_ACCESS_TOKEN": "access",
            "ZARA_CALENDAR_GOOGLE_REFRESH_TOKEN": "refresh",
            "ZARA_CALENDAR_GOOGLE_CLIENT_ID": "client",
            "ZARA_CALENDAR_GOOGLE_CLIENT_SECRET": "secret",
            "ZARA_CALENDAR_CALDAV_URL": "https://calendar.example.test/dav/work/",
            "ZARA_CALENDAR_CALDAV_USERNAME": "me",
            "ZARA_CALENDAR_CALDAV_PASSWORD": "secret",
        }
        with patch.dict(os.environ, env, clear=True):
            with self.assertRaisesRegex(CalendarError, "multiple calendar providers"):
                _backend_from_environment()

    def test_explicit_backend_rejects_incomplete_provider_configuration(self):
        with patch.dict(
            os.environ,
            {
                "ZARA_CALENDAR_BACKEND": "caldav",
                "ZARA_CALENDAR_CALDAV_URL": "https://calendar.example.test/dav/work/",
                "ZARA_CALENDAR_CALDAV_USERNAME": "me",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(CalendarError, "CalDAV"):
                _backend_from_environment()

    def test_unknown_backend_name_fails_closed(self):
        with patch.dict(os.environ, {"ZARA_CALENDAR_BACKEND": "magic"}, clear=True):
            with self.assertRaisesRegex(CalendarError, "calendar backend"):
                _backend_from_environment()


if __name__ == "__main__":
    unittest.main()
