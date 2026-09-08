from __future__ import annotations

import json
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


API_ORIGIN = "https://www.googleapis.com"
API_ROOT = API_ORIGIN + "/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
_TOKEN_RE = re.compile(r"^[\x21-\x7e]+$")


class GoogleCalendarError(RuntimeError):
    pass


class GoogleCalendarBackend:
    def __init__(
        self,
        *,
        access_token: str,
        refresh_token: str,
        client_id: str,
        client_secret: str,
        default_calendar_id: str = "primary",
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_048_576,
        opener=urlopen,
    ) -> None:
        self._access_token = access_token
        self._refresh_token = refresh_token
        self._client_id = client_id
        self._client_secret = client_secret
        self.default_calendar_id = default_calendar_id
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self._opener = opener

    @staticmethod
    def _credential(value: str) -> str:
        if not isinstance(value, str) or not value or len(value) > 8192 or _TOKEN_RE.fullmatch(value) is None:
            raise GoogleCalendarError("invalid credential")
        return value

    @staticmethod
    def _event_time(value):
        if not isinstance(value, dict):
            raise GoogleCalendarError("provider returned malformed event")
        result = value.get("dateTime")
        if not isinstance(result, str) or not result:
            raise GoogleCalendarError("provider returned unsupported all-day or malformed event")
        return result

    def _normalize_event(self, payload, calendar_id=None):
        if not isinstance(payload, dict):
            raise GoogleCalendarError("provider returned malformed event")
        event_id = payload.get("id")
        version = payload.get("etag")
        title = payload.get("summary", "(untitled)")
        if not all(isinstance(value, str) and value for value in (event_id, version, title)):
            raise GoogleCalendarError("provider returned malformed event")
        start = self._event_time(payload.get("start"))
        end = self._event_time(payload.get("end"))
        tz = payload.get("start", {}).get("timeZone") or payload.get("end", {}).get("timeZone") or "UTC"
        attendees = payload.get("attendees", [])
        if not isinstance(attendees, list):
            raise GoogleCalendarError("provider returned malformed event")
        normalized_attendees = []
        for attendee in attendees:
            email = attendee.get("email") if isinstance(attendee, dict) else None
            if not isinstance(email, str) or not email:
                raise GoogleCalendarError("provider returned malformed event")
            normalized_attendees.append(email)
        recurrence_values = payload.get("recurrence")
        recurrence = None
        if recurrence_values is not None:
            if not isinstance(recurrence_values, list) or len(recurrence_values) != 1 or not isinstance(recurrence_values[0], str):
                raise GoogleCalendarError("provider returned malformed recurrence")
            recurrence = {"rrule": recurrence_values[0]}
        reminders = []
        reminder_payload = payload.get("reminders", {})
        if isinstance(reminder_payload, dict):
            for override in reminder_payload.get("overrides", []) or []:
                if not isinstance(override, dict) or override.get("method") != "popup" or type(override.get("minutes")) is not int:
                    raise GoogleCalendarError("provider returned malformed reminders")
                reminders.append({"minutes_before": override["minutes"]})
        return {
            "event_id": event_id,
            "calendar_id": calendar_id or self.default_calendar_id,
            "title": title,
            "start": start,
            "end": end,
            "timezone": tz,
            "attendees": normalized_attendees,
            "recurrence": recurrence,
            "reminders": reminders,
            "version": version,
        }

    def _read_json(self, response):
        body = response.read(self.max_response_bytes + 1)
        if len(body) > self.max_response_bytes:
            raise GoogleCalendarError("provider response too large")
        try:
            value = json.loads(body.decode("utf-8")) if body else {}
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GoogleCalendarError("provider returned malformed JSON") from error
        if not isinstance(value, dict):
            raise GoogleCalendarError("provider returned malformed JSON")
        return value

    def _refresh(self):
        refresh = self._credential(self._refresh_token)
        client_id = self._credential(self._client_id)
        client_secret = self._credential(self._client_secret)
        body = urlencode({"grant_type": "refresh_token", "refresh_token": refresh, "client_id": client_id, "client_secret": client_secret}).encode()
        request = Request(TOKEN_URL, data=body, method="POST", headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self._opener(request, self.timeout_seconds) as response:
                payload = self._read_json(response)
        except (HTTPError, URLError, socket.timeout, TimeoutError, OSError) as error:
            raise GoogleCalendarError("reauth-required") from error
        token = payload.get("access_token")
        self._access_token = self._credential(token)

    def _request(self, method, path, *, query=None, payload=None, expected_version=None, allow_404=False, refreshed=False):
        if not isinstance(path, str) or not path.startswith("/") or "://" in path:
            raise GoogleCalendarError("invalid provider path")
        token = self._credential(self._access_token)
        url = API_ROOT + path
        if query:
            url += "?" + urlencode(query)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        data = None
        if payload is not None:
            data = json.dumps(payload, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        if expected_version is not None:
            headers["If-Match"] = expected_version
        request = Request(url, data=data, method=method, headers=headers)
        try:
            with self._opener(request, self.timeout_seconds) as response:
                return self._read_json(response)
        except HTTPError as error:
            if error.code == 404 and allow_404:
                return None
            if error.code == 401 and not refreshed:
                self._refresh()
                return self._request(method, path, query=query, payload=payload, expected_version=expected_version, allow_404=allow_404, refreshed=True)
            if error.code in (409, 412):
                raise GoogleCalendarError("stale-version") from error
            if error.code == 401:
                raise GoogleCalendarError("reauth-required") from error
            raise GoogleCalendarError(f"provider-http-{error.code}") from error
        except (URLError, socket.timeout, TimeoutError, OSError) as error:
            raise GoogleCalendarError("provider-unavailable") from error

    def search_events(self, start, end, text, calendar_id, limit):
        calendar = calendar_id or self.default_calendar_id
        path = f"/calendars/{quote(calendar, safe='')}/events"
        base_query = {"timeMin": start, "timeMax": end, "singleEvents": "true", "maxResults": min(limit, 2500)}
        if text:
            base_query["q"] = text
        results = []
        page_token = None
        while len(results) < limit:
            query = dict(base_query)
            if page_token:
                query["pageToken"] = page_token
            payload = self._request("GET", path, query=query)
            items = payload.get("items", [])
            if not isinstance(items, list):
                raise GoogleCalendarError("provider returned malformed events page")
            for item in items:
                results.append(self._normalize_event(item, calendar))
                if len(results) >= limit:
                    break
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
            if not isinstance(page_token, str) or len(page_token) > 4096:
                raise GoogleCalendarError("provider returned malformed page token")
        return results

    def get_event(self, event_id):
        path = f"/calendars/{quote(self.default_calendar_id, safe='')}/events/{quote(event_id, safe='')}"
        payload = self._request("GET", path, allow_404=True)
        return None if payload is None else self._normalize_event(payload, self.default_calendar_id)

    @staticmethod
    def _write_payload(event):
        payload = {
            "summary": event["title"],
            "start": {"dateTime": event["start"], "timeZone": event["timezone"]},
            "end": {"dateTime": event["end"], "timeZone": event["timezone"]},
            "attendees": [{"email": value} for value in event["attendees"]],
            "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": value["minutes_before"]} for value in event["reminders"]]},
        }
        if event["recurrence"] is not None:
            payload["recurrence"] = [event["recurrence"]["rrule"]]
        return payload

    def create_event(self, event):
        calendar = event["calendar_id"]
        payload = self._request("POST", f"/calendars/{quote(calendar, safe='')}/events", payload=self._write_payload(event))
        normalized = self._normalize_event(payload, calendar)
        return {"accepted": True, "event_id": normalized["event_id"], "version": normalized["version"]}

    def update_event(self, event_id, expected_version, patch):
        current = self.get_event(event_id)
        if current is None:
            raise GoogleCalendarError("event does not exist")
        current.update(patch)
        payload = self._request("PATCH", f"/calendars/{quote(current['calendar_id'], safe='')}/events/{quote(event_id, safe='')}", payload=self._write_payload(current), expected_version=expected_version)
        normalized = self._normalize_event(payload, current["calendar_id"])
        return {"accepted": True, "event_id": event_id, "version": normalized["version"]}

    def delete_event(self, event_id, expected_version):
        path = f"/calendars/{quote(self.default_calendar_id, safe='')}/events/{quote(event_id, safe='')}"
        self._request("DELETE", path, expected_version=expected_version)
        return {"accepted": True, "event_id": event_id, "version": expected_version}

    def free_busy(self, start, end, calendar_ids):
        payload = self._request("POST", "/freeBusy", payload={"timeMin": start, "timeMax": end, "items": [{"id": value} for value in calendar_ids]})
        calendars = payload.get("calendars")
        if not isinstance(calendars, dict):
            raise GoogleCalendarError("provider returned malformed free/busy data")
        result = []
        for calendar_id in calendar_ids:
            entry = calendars.get(calendar_id)
            if not isinstance(entry, dict) or not isinstance(entry.get("busy", []), list):
                raise GoogleCalendarError("provider returned malformed free/busy data")
            for busy in entry.get("busy", []):
                if not isinstance(busy, dict) or not isinstance(busy.get("start"), str) or not isinstance(busy.get("end"), str):
                    raise GoogleCalendarError("provider returned malformed free/busy data")
                result.append({"calendar_id": calendar_id, "start": busy["start"], "end": busy["end"]})
        return result
