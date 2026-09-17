from __future__ import annotations

import base64
import sys
import unittest
from pathlib import Path

LIB_ROOT = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB_ROOT))

from zara_calendar.caldav import CalDavCalendarBackend, CalDavCalendarError


CALENDAR_URL = "https://calendar.example.test/dav/calendars/me/work/"


class CalDavBasicAuthContractTests(unittest.TestCase):
    def test_basic_username_with_colon_is_rejected_before_encoding(self):
        password = "provider-secret"
        with self.assertRaisesRegex(CalDavCalendarError, "username") as caught:
            CalDavCalendarBackend(
                calendar_url=CALENDAR_URL,
                calendar_id="work",
                username="team:admin",
                password=password,
            )
        self.assertNotIn(password, str(caught.exception))

    def test_basic_password_may_contain_colon_without_changing_user_id(self):
        backend = CalDavCalendarBackend(
            calendar_url=CALENDAR_URL,
            calendar_id="work",
            username="team",
            password="admin:secret",
        )
        scheme, encoded = backend._authorization.split(" ", 1)
        self.assertEqual(scheme, "Basic")
        self.assertEqual(base64.b64decode(encoded).decode("utf-8"), "team:admin:secret")


if __name__ == "__main__":
    unittest.main()
