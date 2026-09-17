from __future__ import annotations

import base64
import re
import socket
import uuid
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


DAV_NS = "DAV:"
CALDAV_NS = "urn:ietf:params:xml:ns:caldav"
_CREDENTIAL_RE = re.compile(r"^[\x20-\x7e]+$")
_EVENT_ID_RE = re.compile(r"^[^/\\\x00-\x1f]{1,240}$")
_TRIGGER_RE = re.compile(r"^-P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?)?$")
_SAFE_UID_RE = re.compile(r"^[A-Za-z0-9._@+-]{1,200}$")

ET.register_namespace("D", DAV_NS)
ET.register_namespace("C", CALDAV_NS)


class CalDavCalendarError(RuntimeError):
    pass


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _default_open(request, timeout):
    return build_opener(_NoRedirectHandler()).open(request, timeout=timeout)


class CalDavCalendarBackend:
    def __init__(
        self,
        *,
        calendar_url: str,
        calendar_id: str = "default",
        username: str | None = None,
        password: str | None = None,
        bearer_token: str | None = None,
        timeout_seconds: float = 10.0,
        max_response_bytes: int = 1_048_576,
        opener=None,
        uid_factory=None,
        clock=None,
    ) -> None:
        self.calendar_url = self._calendar_url(calendar_url)
        self.default_calendar_id = self._text(calendar_id, "calendar id", 256)
        self.timeout_seconds = self._positive_number(timeout_seconds, "timeout_seconds", 120)
        if type(max_response_bytes) is not int or not 1024 <= max_response_bytes <= 16 * 1024 * 1024:
            raise CalDavCalendarError("max_response_bytes is out of range")
        self.max_response_bytes = max_response_bytes
        self._opener = opener or _default_open
        self._uid_factory = uid_factory or (lambda: uuid.uuid4().hex)
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._authorization = self._authorization_header(username, password, bearer_token)
        split = urlsplit(self.calendar_url)
        self._origin = (split.scheme.lower(), split.hostname.lower(), split.port or 443)
        self._collection_path = split.path

    @staticmethod
    def _positive_number(value, name, maximum):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 < value <= maximum:
            raise CalDavCalendarError(f"{name} is out of range")
        return float(value)

    @staticmethod
    def _text(value, name, limit):
        if not isinstance(value, str) or not value.strip():
            raise CalDavCalendarError(f"{name} must be a non-empty string")
        if len(value.encode("utf-8")) > limit or any(ord(ch) < 0x20 for ch in value):
            raise CalDavCalendarError(f"{name} is invalid")
        return value

    @classmethod
    def _credential(cls, value, name):
        if not isinstance(value, str) or not value or len(value) > 8192 or _CREDENTIAL_RE.fullmatch(value) is None:
            raise CalDavCalendarError(f"invalid {name} credential")
        return value

    @classmethod
    def _authorization_header(cls, username, password, bearer_token):
        basic_supplied = username is not None or password is not None
        bearer_supplied = bearer_token is not None
        if basic_supplied and bearer_supplied:
            raise CalDavCalendarError("CalDAV auth mode is ambiguous")
        if bearer_supplied:
            token = cls._credential(bearer_token, "bearer")
            return f"Bearer {token}"
        if not basic_supplied or username is None or password is None:
            raise CalDavCalendarError("CalDAV auth requires Basic credentials or a bearer token")
        user = cls._credential(username, "username")
        secret = cls._credential(password, "password")
        encoded = base64.b64encode(f"{user}:{secret}".encode("utf-8")).decode("ascii")
        return f"Basic {encoded}"

    @staticmethod
    def _calendar_url(value):
        if not isinstance(value, str) or len(value) > 4096:
            raise CalDavCalendarError("CalDAV calendar URL is invalid")
        parsed = urlsplit(value)
        if parsed.scheme.lower() != "https" or not parsed.hostname:
            raise CalDavCalendarError("CalDAV calendar URL must use https")
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise CalDavCalendarError("CalDAV calendar URL is invalid")
        path = parsed.path or "/"
        if not path.endswith("/"):
            path += "/"
        return parsed._replace(path=path, query="", fragment="").geturl()

    def _ensure_calendar(self, calendar_id):
        selected = self.default_calendar_id if calendar_id in (None, "") else calendar_id
        if selected != self.default_calendar_id:
            raise CalDavCalendarError("requested calendar is not the configured calendar")
        return self.default_calendar_id

    def _event_url(self, event_id):
        if not isinstance(event_id, str) or _EVENT_ID_RE.fullmatch(event_id) is None:
            raise CalDavCalendarError("event id is invalid")
        if event_id in {".", ".."} or "://" in event_id:
            raise CalDavCalendarError("event id is invalid")
        return urljoin(self.calendar_url, quote(event_id, safe="-._~"))

    def _same_origin(self, url):
        parsed = urlsplit(url)
        origin = (parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port or 443)
        return origin == self._origin

    def _assert_provider_url(self, url, *, resource=False):
        if not self._same_origin(url):
            raise CalDavCalendarError("CalDAV response escaped configured origin")
        parsed = urlsplit(url)
        if parsed.query or parsed.fragment:
            raise CalDavCalendarError("CalDAV provider URL is invalid")
        path = parsed.path
        if resource:
            if not path.startswith(self._collection_path) or path == self._collection_path:
                raise CalDavCalendarError("CalDAV resource escaped configured collection")
            remainder = path[len(self._collection_path) :]
            if "/" in remainder:
                raise CalDavCalendarError("CalDAV resource escaped configured collection")
        elif path != self._collection_path:
            raise CalDavCalendarError("CalDAV response escaped configured collection")

    @staticmethod
    def _header(headers, name):
        if headers is None:
            return None
        value = headers.get(name)
        if value is not None:
            return value
        target = name.lower()
        for key, candidate in getattr(headers, "items", lambda: ())():
            if str(key).lower() == target:
                return candidate
        return None

    @classmethod
    def _etag(cls, value):
        if not isinstance(value, str) or not value or len(value) > 256:
            raise CalDavCalendarError("provider returned invalid ETag")
        if value.startswith("W/") or any(ord(ch) < 0x20 for ch in value):
            raise CalDavCalendarError("provider returned invalid ETag")
        return value

    def _request(
        self,
        method,
        url,
        *,
        body=None,
        headers=None,
        allow_404=False,
        resource=False,
    ):
        self._assert_provider_url(url, resource=resource)
        request_headers = {
            "Authorization": self._authorization,
            "Accept": "application/xml, text/calendar;q=0.9, */*;q=0.1",
        }
        request_headers.update(headers or {})
        request = Request(url, data=body, method=method, headers=request_headers)
        try:
            with self._opener(request, self.timeout_seconds) as response:
                final_url = response.geturl() if hasattr(response, "geturl") else url
                self._assert_provider_url(final_url, resource=resource)
                payload = response.read(self.max_response_bytes + 1)
                if len(payload) > self.max_response_bytes:
                    raise CalDavCalendarError("provider response too large")
                return payload, response.headers, final_url
        except HTTPError as error:
            if error.code == 404 and allow_404:
                return None
            if error.code in (409, 412):
                raise CalDavCalendarError("stale-version") from error
            if error.code in (401, 403):
                raise CalDavCalendarError("CalDAV authentication failed") from error
            if 300 <= error.code < 400:
                raise CalDavCalendarError("CalDAV redirect refused") from error
            raise CalDavCalendarError(f"provider-http-{error.code}") from error
        except (URLError, socket.timeout, TimeoutError, OSError) as error:
            raise CalDavCalendarError("CalDAV provider unavailable") from error

    @staticmethod
    def _utc_stamp(value):
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as error:
            raise CalDavCalendarError("calendar time is invalid") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise CalDavCalendarError("calendar time must include timezone information")
        return parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    @staticmethod
    def _query_xml(start, end, text=None):
        root = ET.Element(f"{{{CALDAV_NS}}}calendar-query")
        prop = ET.SubElement(root, f"{{{DAV_NS}}}prop")
        ET.SubElement(prop, f"{{{DAV_NS}}}getetag")
        calendar_data = ET.SubElement(prop, f"{{{CALDAV_NS}}}calendar-data")
        ET.SubElement(
            calendar_data,
            f"{{{CALDAV_NS}}}expand",
            {"start": CalDavCalendarBackend._utc_stamp(start), "end": CalDavCalendarBackend._utc_stamp(end)},
        )
        filter_node = ET.SubElement(root, f"{{{CALDAV_NS}}}filter")
        vcalendar = ET.SubElement(filter_node, f"{{{CALDAV_NS}}}comp-filter", {"name": "VCALENDAR"})
        vevent = ET.SubElement(vcalendar, f"{{{CALDAV_NS}}}comp-filter", {"name": "VEVENT"})
        ET.SubElement(
            vevent,
            f"{{{CALDAV_NS}}}time-range",
            {"start": CalDavCalendarBackend._utc_stamp(start), "end": CalDavCalendarBackend._utc_stamp(end)},
        )
        if text:
            summary = ET.SubElement(vevent, f"{{{CALDAV_NS}}}prop-filter", {"name": "SUMMARY"})
            match = ET.SubElement(summary, f"{{{CALDAV_NS}}}text-match", {"collation": "i;unicode-casemap"})
            match.text = text
        return ET.tostring(root, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _unfold_lines(payload):
        if not isinstance(payload, str):
            raise CalDavCalendarError("provider returned malformed iCalendar")
        raw_lines = payload.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        lines = []
        for line in raw_lines:
            if line.startswith((" ", "\t")):
                if not lines:
                    raise CalDavCalendarError("provider returned malformed iCalendar folding")
                lines[-1] += line[1:]
            else:
                lines.append(line)
        return lines

    @staticmethod
    def _property(line):
        if ":" not in line:
            raise CalDavCalendarError("provider returned malformed iCalendar property")
        head, value = line.split(":", 1)
        parts = head.split(";")
        name = parts[0].upper()
        params = {}
        for item in parts[1:]:
            if "=" not in item:
                raise CalDavCalendarError("provider returned malformed iCalendar parameter")
            key, param_value = item.split("=", 1)
            params[key.upper()] = param_value.strip('"')
        return name, params, value

    @staticmethod
    def _unescape_text(value):
        result = []
        index = 0
        while index < len(value):
            char = value[index]
            if char != "\\":
                result.append(char)
                index += 1
                continue
            if index + 1 >= len(value):
                raise CalDavCalendarError("provider returned malformed escaped text")
            escaped = value[index + 1]
            if escaped in ("\\", ",", ";"):
                result.append(escaped)
            elif escaped in ("n", "N"):
                result.append(" ")
            else:
                result.append(escaped)
            index += 2
        return "".join(result)

    @staticmethod
    def _parse_time(params, value):
        if params.get("VALUE", "").upper() == "DATE" or "T" not in value:
            raise CalDavCalendarError("provider returned unsupported all-day event")
        if value.endswith("Z"):
            try:
                parsed = datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
            except ValueError as error:
                raise CalDavCalendarError("provider returned malformed event time") from error
            return parsed.isoformat(), "UTC"
        tzid = params.get("TZID")
        if not tzid:
            raise CalDavCalendarError("provider returned floating event time")
        try:
            zone = ZoneInfo(tzid)
            parsed = datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=zone)
        except (ValueError, ZoneInfoNotFoundError) as error:
            raise CalDavCalendarError("provider returned malformed event timezone") from error
        return parsed.isoformat(), tzid

    @staticmethod
    def _trigger_minutes(value):
        match = _TRIGGER_RE.fullmatch(value)
        if match is None:
            raise CalDavCalendarError("provider returned unsupported reminder trigger")
        days = int(match.group("days") or 0)
        hours = int(match.group("hours") or 0)
        minutes = int(match.group("minutes") or 0)
        total = days * 1440 + hours * 60 + minutes
        if not 0 <= total <= 10080:
            raise CalDavCalendarError("provider returned reminder outside supported range")
        return total

    @classmethod
    def _parse_ical(cls, payload):
        lines = cls._unfold_lines(payload)
        events = []
        event_props = None
        alarm_props = None
        alarms = None
        for line in lines:
            upper = line.upper()
            if upper == "BEGIN:VEVENT":
                if event_props is not None:
                    raise CalDavCalendarError("provider returned nested VEVENT")
                event_props = []
                alarms = []
                continue
            if upper == "END:VEVENT":
                if event_props is None or alarm_props is not None:
                    raise CalDavCalendarError("provider returned malformed VEVENT")
                events.append(cls._normalize_vevent(event_props, alarms))
                event_props = None
                alarms = None
                continue
            if event_props is None:
                continue
            if upper == "BEGIN:VALARM":
                if alarm_props is not None:
                    raise CalDavCalendarError("provider returned nested VALARM")
                alarm_props = []
                continue
            if upper == "END:VALARM":
                if alarm_props is None:
                    raise CalDavCalendarError("provider returned malformed VALARM")
                alarms.append(alarm_props)
                alarm_props = None
                continue
            prop = cls._property(line)
            if alarm_props is not None:
                alarm_props.append(prop)
            else:
                event_props.append(prop)
        if event_props is not None or alarm_props is not None:
            raise CalDavCalendarError("provider returned unterminated iCalendar component")
        if not events:
            raise CalDavCalendarError("provider returned calendar without VEVENT")
        return events

    @classmethod
    def _normalize_vevent(cls, props, alarms):
        values = {}
        for name, params, value in props:
            values.setdefault(name, []).append((params, value))

        uid_values = values.get("UID", [])
        start_values = values.get("DTSTART", [])
        end_values = values.get("DTEND", [])
        if len(uid_values) != 1 or len(start_values) != 1 or len(end_values) != 1:
            raise CalDavCalendarError("provider returned malformed VEVENT")
        uid = cls._text(uid_values[0][1], "provider UID", 512)
        start, timezone_name = cls._parse_time(*start_values[0])
        end, end_timezone = cls._parse_time(*end_values[0])
        if end_timezone != timezone_name:
            raise CalDavCalendarError("provider returned event with mismatched timezones")

        summary_values = values.get("SUMMARY", [])
        title = "(untitled)"
        if summary_values:
            if len(summary_values) != 1:
                raise CalDavCalendarError("provider returned duplicate SUMMARY")
            title = cls._unescape_text(summary_values[0][1]) or "(untitled)"
        cls._text(title, "provider summary", 1024)

        attendees = []
        for _, attendee_value in values.get("ATTENDEE", []):
            if not attendee_value.lower().startswith("mailto:"):
                raise CalDavCalendarError("provider returned unsupported attendee")
            attendees.append(cls._text(attendee_value[7:], "provider attendee", 320))

        recurrence = None
        rrules = values.get("RRULE", [])
        if rrules:
            if len(rrules) != 1:
                raise CalDavCalendarError("provider returned duplicate RRULE")
            recurrence = {"rrule": "RRULE:" + cls._text(rrules[0][1], "provider RRULE", 2048)}

        reminders = []
        for alarm in alarms:
            alarm_values = {}
            for name, params, value in alarm:
                alarm_values.setdefault(name, []).append((params, value))
            action = alarm_values.get("ACTION", [])
            trigger = alarm_values.get("TRIGGER", [])
            if len(action) != 1 or action[0][1].upper() != "DISPLAY":
                continue
            if len(trigger) != 1:
                raise CalDavCalendarError("provider returned malformed DISPLAY alarm")
            reminders.append({"minutes_before": cls._trigger_minutes(trigger[0][1])})

        transparency_values = values.get("TRANSP", [])
        transparent = bool(transparency_values and transparency_values[0][1].upper() == "TRANSPARENT")
        return {
            "title": title,
            "start": start,
            "end": end,
            "timezone": timezone_name,
            "attendees": attendees,
            "recurrence": recurrence,
            "reminders": reminders,
            "_uid": uid,
            "_transparent": transparent,
        }

    def _resource_id_from_href(self, href):
        if not isinstance(href, str) or not href:
            raise CalDavCalendarError("provider returned malformed href")
        absolute = urljoin(self.calendar_url, href)
        self._assert_provider_url(absolute, resource=True)
        parsed = urlsplit(absolute)
        remainder = parsed.path[len(self._collection_path) :]
        event_id = unquote(remainder)
        if _EVENT_ID_RE.fullmatch(event_id) is None or event_id in {".", ".."}:
            raise CalDavCalendarError("provider returned invalid event id")
        return event_id

    def _parse_multistatus(self, payload):
        try:
            root = ET.fromstring(payload)
        except ET.ParseError as error:
            raise CalDavCalendarError("provider returned malformed XML") from error
        if root.tag != f"{{{DAV_NS}}}multistatus":
            raise CalDavCalendarError("provider returned malformed XML multistatus")
        results = []
        for response in root.findall(f"{{{DAV_NS}}}response"):
            href_node = response.find(f"{{{DAV_NS}}}href")
            if href_node is None or not href_node.text:
                raise CalDavCalendarError("provider returned response without href")
            event_id = self._resource_id_from_href(href_node.text)
            selected = None
            for propstat in response.findall(f"{{{DAV_NS}}}propstat"):
                status = propstat.find(f"{{{DAV_NS}}}status")
                if status is not None and status.text and " 200 " in status.text:
                    selected = propstat.find(f"{{{DAV_NS}}}prop")
                    break
            if selected is None:
                continue
            etag_node = selected.find(f"{{{DAV_NS}}}getetag")
            data_node = selected.find(f"{{{CALDAV_NS}}}calendar-data")
            if etag_node is None or data_node is None or etag_node.text is None or data_node.text is None:
                raise CalDavCalendarError("provider returned incomplete CalDAV event")
            etag = self._etag(etag_node.text)
            parsed_events = self._parse_ical(data_node.text)
            if not parsed_events:
                continue
            event = dict(parsed_events[0])
            event.update(
                {
                    "event_id": event_id,
                    "calendar_id": self.default_calendar_id,
                    "version": etag,
                }
            )
            results.append(event)
        return results

    def _report(self, start, end, text=None):
        body = self._query_xml(start, end, text)
        response = self._request(
            "REPORT",
            self.calendar_url,
            body=body,
            headers={
                "Content-Type": "application/xml; charset=utf-8",
                "Depth": "1",
            },
        )
        return self._parse_multistatus(response[0])

    @staticmethod
    def _public_event(event):
        return {key: value for key, value in event.items() if not key.startswith("_")}

    def search_events(self, start, end, text, calendar_id, limit):
        self._ensure_calendar(calendar_id)
        if type(limit) is not int or not 1 <= limit <= 200:
            raise CalDavCalendarError("result limit is invalid")
        if text is not None:
            self._text(text, "search text", 1024)
        values = self._report(start, end, text)
        return [self._public_event(value) for value in values[:limit]]

    def _get_raw_event(self, event_id):
        url = self._event_url(event_id)
        response = self._request("GET", url, allow_404=True, resource=True)
        if response is None:
            return None
        body, headers, _ = response
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError as error:
            raise CalDavCalendarError("provider returned malformed iCalendar encoding") from error
        parsed = self._parse_ical(text)[0]
        parsed.update(
            {
                "event_id": event_id,
                "calendar_id": self.default_calendar_id,
                "version": self._etag(self._header(headers, "ETag")),
            }
        )
        return parsed

    def get_event(self, event_id):
        value = self._get_raw_event(event_id)
        return None if value is None else self._public_event(value)

    @staticmethod
    def _escape_text(value):
        return value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")

    @staticmethod
    def _format_event_time(value, timezone_name):
        try:
            parsed = datetime.fromisoformat(value)
        except (TypeError, ValueError) as error:
            raise CalDavCalendarError("event time is invalid") from error
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise CalDavCalendarError("event time must include timezone information")
        if timezone_name.upper() in {"UTC", "ETC/UTC", "GMT"}:
            return None, parsed.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError as error:
            raise CalDavCalendarError("event timezone is invalid") from error
        return timezone_name, parsed.astimezone(zone).strftime("%Y%m%dT%H%M%S")

    @classmethod
    def _validate_email(cls, value):
        email = cls._text(value, "attendee", 320)
        if "@" not in email or any(char in email for char in "<>\";, "):
            raise CalDavCalendarError("attendee is invalid")
        return email

    @classmethod
    def _build_ical(cls, event, uid, stamp):
        uid = cls._text(uid, "event UID", 512)
        title = cls._text(event.get("title"), "title", 1024)
        timezone_name = cls._text(event.get("timezone"), "timezone", 128)
        start_tzid, start_value = cls._format_event_time(event.get("start"), timezone_name)
        end_tzid, end_value = cls._format_event_time(event.get("end"), timezone_name)
        if start_tzid != end_tzid:
            raise CalDavCalendarError("event start/end timezone mismatch")

        attendees = event.get("attendees")
        reminders = event.get("reminders")
        recurrence = event.get("recurrence")
        if not isinstance(attendees, list) or len(attendees) > 128:
            raise CalDavCalendarError("attendees are invalid")
        if not isinstance(reminders, list) or len(reminders) > 32:
            raise CalDavCalendarError("reminders are invalid")

        lines = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Zara//CalDAV Client//EN",
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"DTSTAMP:{stamp.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}",
        ]
        if start_tzid:
            lines.append(f"DTSTART;TZID={start_tzid}:{start_value}")
            lines.append(f"DTEND;TZID={end_tzid}:{end_value}")
        else:
            lines.append(f"DTSTART:{start_value}")
            lines.append(f"DTEND:{end_value}")
        lines.append(f"SUMMARY:{cls._escape_text(title)}")
        for attendee in attendees:
            lines.append(f"ATTENDEE:mailto:{cls._validate_email(attendee)}")
        if recurrence is not None:
            if not isinstance(recurrence, dict) or set(recurrence) != {"rrule"}:
                raise CalDavCalendarError("recurrence is invalid")
            rule = cls._text(recurrence["rrule"], "recurrence rule", 2048)
            if rule.upper().startswith("RRULE:"):
                rule = rule[6:]
            if "\r" in rule or "\n" in rule:
                raise CalDavCalendarError("recurrence is invalid")
            lines.append("RRULE:" + rule)
        for reminder in reminders:
            if not isinstance(reminder, dict) or set(reminder) != {"minutes_before"}:
                raise CalDavCalendarError("reminder is invalid")
            minutes = reminder["minutes_before"]
            if type(minutes) is not int or not 0 <= minutes <= 10080:
                raise CalDavCalendarError("reminder is invalid")
            days, remainder = divmod(minutes, 1440)
            hours, minute_value = divmod(remainder, 60)
            duration = "-P"
            if days:
                duration += f"{days}D"
            if hours or minute_value or not days:
                duration += "T"
                if hours:
                    duration += f"{hours}H"
                if minute_value or not hours:
                    duration += f"{minute_value}M"
            lines.extend(
                [
                    "BEGIN:VALARM",
                    "ACTION:DISPLAY",
                    f"TRIGGER:{duration}",
                    "DESCRIPTION:Zara calendar reminder",
                    "END:VALARM",
                ]
            )
        lines.extend(["END:VEVENT", "END:VCALENDAR", ""])
        return "\r\n".join(lines).encode("utf-8")

    def _version_after_write(self, headers, event_id):
        value = self._header(headers, "ETag")
        if value is not None:
            return self._etag(value)
        observed = self._get_raw_event(event_id)
        if observed is None:
            raise CalDavCalendarError("provider write acknowledged but resource is absent")
        return observed["version"]

    def create_event(self, event):
        self._ensure_calendar(event.get("calendar_id"))
        raw_uid = str(self._uid_factory())
        if _SAFE_UID_RE.fullmatch(raw_uid) is None:
            raise CalDavCalendarError("generated event UID is invalid")
        event_id = f"zara-{raw_uid}.ics"
        url = self._event_url(event_id)
        body = self._build_ical(event, raw_uid, self._clock())
        response = self._request(
            "PUT",
            url,
            body=body,
            headers={
                "Content-Type": "text/calendar; charset=utf-8",
                "If-None-Match": "*",
            },
            resource=True,
        )
        version = self._version_after_write(response[1], event_id)
        return {"accepted": True, "event_id": event_id, "version": version}

    def update_event(self, event_id, expected_version, patch):
        expected_version = self._etag(expected_version)
        current = self._get_raw_event(event_id)
        if current is None:
            raise CalDavCalendarError("event does not exist")
        if not isinstance(patch, dict) or not patch:
            raise CalDavCalendarError("patch must be a non-empty object")
        allowed = {"title", "start", "end", "timezone", "attendees", "recurrence", "reminders"}
        if set(patch) - allowed:
            raise CalDavCalendarError("patch contains unsupported fields")
        merged = self._public_event(current)
        merged.update(patch)
        body = self._build_ical(merged, current["_uid"], self._clock())
        response = self._request(
            "PUT",
            self._event_url(event_id),
            body=body,
            headers={
                "Content-Type": "text/calendar; charset=utf-8",
                "If-Match": expected_version,
            },
            resource=True,
        )
        version = self._version_after_write(response[1], event_id)
        return {"accepted": True, "event_id": event_id, "version": version}

    def delete_event(self, event_id, expected_version):
        expected_version = self._etag(expected_version)
        self._request(
            "DELETE",
            self._event_url(event_id),
            headers={"If-Match": expected_version},
            resource=True,
        )
        return {"accepted": True, "event_id": event_id, "version": expected_version}

    def free_busy(self, start, end, calendar_ids):
        if not isinstance(calendar_ids, list) or not calendar_ids:
            raise CalDavCalendarError("calendar_ids are invalid")
        for calendar_id in calendar_ids:
            self._ensure_calendar(calendar_id)
        values = self._report(start, end, None)
        result = []
        for event in values:
            if event.get("_transparent"):
                continue
            result.append(
                {
                    "calendar_id": self.default_calendar_id,
                    "event_id": event["event_id"],
                    "start": event["start"],
                    "end": event["end"],
                }
            )
        return result
