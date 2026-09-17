from __future__ import annotations

import csv
import hashlib
import io
import math
import zipfile
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable


class GTFSFeedError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeedLimits:
    max_archive_bytes: int = 16 * 1024 * 1024
    max_uncompressed_bytes: int = 96 * 1024 * 1024
    max_member_bytes: int = 32 * 1024 * 1024
    max_members: int = 64
    max_rows_per_file: int = 1_000_000
    max_field_bytes: int = 1024 * 1024


@dataclass(frozen=True)
class Route:
    route_id: str
    short_name: str
    long_name: str
    route_type: str
    color: str
    text_color: str


@dataclass(frozen=True)
class Stop:
    stop_id: str
    name: str
    latitude: float
    longitude: float


@dataclass(frozen=True)
class Trip:
    trip_id: str
    route_id: str
    service_id: str
    headsign: str
    direction_id: str
    shape_id: str


@dataclass(frozen=True)
class StopTime:
    trip_id: str
    arrival_time: str
    departure_time: str
    stop_id: str
    stop_sequence: int


@dataclass(frozen=True)
class CalendarRule:
    service_id: str
    weekdays: tuple[bool, bool, bool, bool, bool, bool, bool]
    start_date: str
    end_date: str


@dataclass(frozen=True)
class StaticSnapshot:
    generation: str
    source: str
    routes: dict[str, Route]
    stops: dict[str, Stop]
    trips: dict[str, Trip]
    stop_times_by_stop: dict[str, tuple[StopTime, ...]]
    stop_times_by_trip: dict[str, tuple[StopTime, ...]]
    calendars: dict[str, CalendarRule]
    calendar_exceptions: dict[tuple[str, str], int]
    shapes: dict[str, tuple[tuple[float, float], ...]]

    def route(self, route_id: str) -> dict:
        route = self.routes.get(route_id)
        if route is None:
            raise GTFSFeedError("unknown route")
        return _route_dict(route)

    def route_list(self, limit: int = 100) -> list[dict]:
        limit = _bounded_limit(limit, 1, 500)
        routes = sorted(
            self.routes.values(),
            key=lambda route: (route.short_name, route.long_name, route.route_id),
        )
        return [_route_dict(route) for route in routes[:limit]]

    def stop(self, stop_id: str) -> dict:
        stop = self.stops.get(stop_id)
        if stop is None:
            raise GTFSFeedError("unknown stop")
        return _stop_dict(stop)

    def stops_near(
        self,
        latitude: float,
        longitude: float,
        radius_m: float = 1000.0,
        limit: int = 20,
    ) -> list[dict]:
        latitude, longitude = _coordinates(latitude, longitude)
        if not 1.0 <= float(radius_m) <= 50_000.0:
            raise GTFSFeedError("radius_m must be between 1 and 50000")
        limit = _bounded_limit(limit, 1, 100)
        matches = []
        for stop in self.stops.values():
            distance = _haversine_m(
                latitude,
                longitude,
                stop.latitude,
                stop.longitude,
            )
            if distance <= radius_m:
                item = _stop_dict(stop)
                item["distance_m"] = round(distance, 1)
                matches.append(item)
        matches.sort(key=lambda item: (item["distance_m"], item["stop_id"]))
        return matches[:limit]

    def route_stops(
        self,
        route_id: str,
        direction_id: str = "",
        limit: int = 500,
    ) -> list[dict]:
        if route_id not in self.routes:
            raise GTFSFeedError("unknown route")
        limit = _bounded_limit(limit, 1, 2000)
        seen: set[str] = set()
        ordered: list[dict] = []
        candidates = sorted(
            (
                trip
                for trip in self.trips.values()
                if trip.route_id == route_id
                and (not direction_id or trip.direction_id == direction_id)
            ),
            key=lambda trip: trip.trip_id,
        )
        for trip in candidates:
            for stop_time in self.stop_times_by_trip.get(trip.trip_id, ()):
                if stop_time.stop_id in seen:
                    continue
                stop = self.stops.get(stop_time.stop_id)
                if stop is None:
                    continue
                seen.add(stop.stop_id)
                ordered.append(_stop_dict(stop))
                if len(ordered) >= limit:
                    return ordered
        return ordered

    def departures(
        self,
        stop_id: str,
        service_date: str,
        after_time: str = "00:00:00",
        limit: int = 20,
    ) -> list[dict]:
        if stop_id not in self.stops:
            raise GTFSFeedError("unknown stop")
        day = _gtfs_date(service_date)
        after_seconds = _time_seconds(after_time)
        limit = _bounded_limit(limit, 1, 100)
        rows = []
        for stop_time in self.stop_times_by_stop.get(stop_id, ()):
            departure_seconds = _time_seconds(stop_time.departure_time)
            if departure_seconds < after_seconds:
                continue
            trip = self.trips.get(stop_time.trip_id)
            if trip is None or not self.service_active(trip.service_id, day):
                continue
            route = self.routes.get(trip.route_id)
            if route is None:
                continue
            rows.append(
                {
                    "stop_id": stop_id,
                    "trip_id": trip.trip_id,
                    "route_id": trip.route_id,
                    "route_short_name": route.short_name,
                    "headsign": trip.headsign,
                    "direction_id": trip.direction_id,
                    "scheduled_departure": stop_time.departure_time,
                    "departure_source": "scheduled",
                    "static_generation": self.generation,
                }
            )
        rows.sort(
            key=lambda row: (
                _time_seconds(row["scheduled_departure"]),
                row["trip_id"],
            )
        )
        return rows[:limit]

    def route_geometry(self, route_id: str, direction_id: str = "") -> dict:
        if route_id not in self.routes:
            raise GTFSFeedError("unknown route")
        trips = sorted(
            (
                trip
                for trip in self.trips.values()
                if trip.route_id == route_id
                and (not direction_id or trip.direction_id == direction_id)
            ),
            key=lambda trip: trip.trip_id,
        )
        for trip in trips:
            if trip.shape_id and trip.shape_id in self.shapes:
                return {
                    "route_id": route_id,
                    "direction_id": trip.direction_id,
                    "geometry_source": "gtfs_shape",
                    "coordinates": [
                        [longitude, latitude]
                        for latitude, longitude in self.shapes[trip.shape_id]
                    ],
                    "static_generation": self.generation,
                }
        stops = self.route_stops(route_id, direction_id=direction_id)
        return {
            "route_id": route_id,
            "direction_id": direction_id,
            "geometry_source": "stop_sequence",
            "coordinates": [
                [stop["longitude"], stop["latitude"]]
                for stop in stops
            ],
            "static_generation": self.generation,
        }

    def service_active(self, service_id: str, day: date) -> bool:
        key = (service_id, day.strftime("%Y%m%d"))
        exception = self.calendar_exceptions.get(key)
        if exception == 1:
            return True
        if exception == 2:
            return False
        rule = self.calendars.get(service_id)
        if rule is None:
            return not self.calendars
        value = day.strftime("%Y%m%d")
        if value < rule.start_date or value > rule.end_date:
            return False
        return rule.weekdays[day.weekday()]


def load_static_gtfs(
    payload: bytes,
    *,
    source: str,
    limits: FeedLimits | None = None,
) -> StaticSnapshot:
    limits = limits or FeedLimits()
    if not isinstance(payload, bytes):
        raise TypeError("GTFS payload must be bytes")
    if not payload or len(payload) > limits.max_archive_bytes:
        raise GTFSFeedError("GTFS archive size is outside allowed bounds")

    try:
        archive = zipfile.ZipFile(io.BytesIO(payload))
    except (zipfile.BadZipFile, OSError) as error:
        raise GTFSFeedError("invalid GTFS ZIP archive") from error

    with archive:
        members = archive.infolist()
        if len(members) > limits.max_members:
            raise GTFSFeedError("GTFS archive has too many members")
        total_size = 0
        for member in members:
            _validate_member_name(member.filename)
            if member.file_size > limits.max_member_bytes:
                raise GTFSFeedError("GTFS member exceeds size limit")
            total_size += member.file_size
            if total_size > limits.max_uncompressed_bytes:
                raise GTFSFeedError("GTFS archive exceeds uncompressed size limit")

        tables = {
            "routes.txt": _read_table(archive, "routes.txt", limits),
            "stops.txt": _read_table(archive, "stops.txt", limits),
            "trips.txt": _read_table(archive, "trips.txt", limits),
            "stop_times.txt": _read_table(archive, "stop_times.txt", limits),
        }
        for optional in ("calendar.txt", "calendar_dates.txt", "shapes.txt"):
            if optional in archive.namelist():
                tables[optional] = _read_table(archive, optional, limits)
            else:
                tables[optional] = []

    routes = _routes(tables["routes.txt"])
    stops = _stops(tables["stops.txt"])
    trips = _trips(tables["trips.txt"], routes)
    stop_times_by_stop, stop_times_by_trip = _stop_times(
        tables["stop_times.txt"],
        trips,
        stops,
    )
    calendars = _calendars(tables["calendar.txt"])
    calendar_exceptions = _calendar_exceptions(tables["calendar_dates.txt"])
    shapes = _shapes(tables["shapes.txt"])

    return StaticSnapshot(
        generation=hashlib.sha256(payload).hexdigest(),
        source=str(source),
        routes=routes,
        stops=stops,
        trips=trips,
        stop_times_by_stop={
            key: tuple(sorted(value, key=lambda item: (item.stop_sequence, item.trip_id)))
            for key, value in stop_times_by_stop.items()
        },
        stop_times_by_trip={
            key: tuple(sorted(value, key=lambda item: item.stop_sequence))
            for key, value in stop_times_by_trip.items()
        },
        calendars=calendars,
        calendar_exceptions=calendar_exceptions,
        shapes=shapes,
    )


def _read_table(
    archive: zipfile.ZipFile,
    name: str,
    limits: FeedLimits,
) -> list[dict[str, str]]:
    try:
        raw = archive.read(name)
    except KeyError as error:
        raise GTFSFeedError(f"missing required GTFS table: {name}") from error
    if len(raw) > limits.max_member_bytes:
        raise GTFSFeedError("GTFS table exceeds size limit")
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise GTFSFeedError(f"GTFS table is not UTF-8: {name}") from error
    previous_limit = csv.field_size_limit()
    csv.field_size_limit(limits.max_field_bytes)
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if reader.fieldnames is None:
            raise GTFSFeedError(f"GTFS table has no header: {name}")
        rows = []
        for index, row in enumerate(reader, start=1):
            if index > limits.max_rows_per_file:
                raise GTFSFeedError(f"GTFS table has too many rows: {name}")
            rows.append({str(key): str(value or "") for key, value in row.items()})
        return rows
    except csv.Error as error:
        raise GTFSFeedError(f"malformed GTFS CSV: {name}") from error
    finally:
        csv.field_size_limit(previous_limit)


def _routes(rows: Iterable[dict[str, str]]) -> dict[str, Route]:
    result = {}
    for row in rows:
        route_id = _required(row, "route_id", "routes.txt")
        if route_id in result:
            raise GTFSFeedError("duplicate route_id")
        result[route_id] = Route(
            route_id=route_id,
            short_name=row.get("route_short_name", "").strip(),
            long_name=row.get("route_long_name", "").strip(),
            route_type=row.get("route_type", "").strip(),
            color=row.get("route_color", "").strip(),
            text_color=row.get("route_text_color", "").strip(),
        )
    if not result:
        raise GTFSFeedError("routes.txt is empty")
    return result


def _stops(rows: Iterable[dict[str, str]]) -> dict[str, Stop]:
    result = {}
    for row in rows:
        stop_id = _required(row, "stop_id", "stops.txt")
        if stop_id in result:
            raise GTFSFeedError("duplicate stop_id")
        latitude = _float_field(row, "stop_lat", "stops.txt")
        longitude = _float_field(row, "stop_lon", "stops.txt")
        latitude, longitude = _coordinates(latitude, longitude)
        result[stop_id] = Stop(
            stop_id=stop_id,
            name=_required(row, "stop_name", "stops.txt"),
            latitude=latitude,
            longitude=longitude,
        )
    if not result:
        raise GTFSFeedError("stops.txt is empty")
    return result


def _trips(
    rows: Iterable[dict[str, str]],
    routes: dict[str, Route],
) -> dict[str, Trip]:
    result = {}
    for row in rows:
        trip_id = _required(row, "trip_id", "trips.txt")
        route_id = _required(row, "route_id", "trips.txt")
        if route_id not in routes:
            raise GTFSFeedError("trip references unknown route")
        if trip_id in result:
            raise GTFSFeedError("duplicate trip_id")
        result[trip_id] = Trip(
            trip_id=trip_id,
            route_id=route_id,
            service_id=_required(row, "service_id", "trips.txt"),
            headsign=row.get("trip_headsign", "").strip(),
            direction_id=row.get("direction_id", "").strip(),
            shape_id=row.get("shape_id", "").strip(),
        )
    if not result:
        raise GTFSFeedError("trips.txt is empty")
    return result


def _stop_times(
    rows: Iterable[dict[str, str]],
    trips: dict[str, Trip],
    stops: dict[str, Stop],
) -> tuple[dict[str, list[StopTime]], dict[str, list[StopTime]]]:
    by_stop: dict[str, list[StopTime]] = {}
    by_trip: dict[str, list[StopTime]] = {}
    for row in rows:
        trip_id = _required(row, "trip_id", "stop_times.txt")
        stop_id = _required(row, "stop_id", "stop_times.txt")
        if trip_id not in trips:
            raise GTFSFeedError("stop time references unknown trip")
        if stop_id not in stops:
            raise GTFSFeedError("stop time references unknown stop")
        arrival = _required(row, "arrival_time", "stop_times.txt")
        departure = _required(row, "departure_time", "stop_times.txt")
        _time_seconds(arrival)
        _time_seconds(departure)
        try:
            sequence = int(_required(row, "stop_sequence", "stop_times.txt"))
        except ValueError as error:
            raise GTFSFeedError("invalid stop_sequence") from error
        if sequence < 0:
            raise GTFSFeedError("invalid stop_sequence")
        item = StopTime(
            trip_id=trip_id,
            arrival_time=arrival,
            departure_time=departure,
            stop_id=stop_id,
            stop_sequence=sequence,
        )
        by_stop.setdefault(stop_id, []).append(item)
        by_trip.setdefault(trip_id, []).append(item)
    if not by_trip:
        raise GTFSFeedError("stop_times.txt is empty")
    return by_stop, by_trip


def _calendars(rows: Iterable[dict[str, str]]) -> dict[str, CalendarRule]:
    result = {}
    weekday_names = (
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    )
    for row in rows:
        service_id = _required(row, "service_id", "calendar.txt")
        if service_id in result:
            raise GTFSFeedError("duplicate calendar service_id")
        weekdays = tuple(row.get(name, "0").strip() == "1" for name in weekday_names)
        start_date = _required(row, "start_date", "calendar.txt")
        end_date = _required(row, "end_date", "calendar.txt")
        _gtfs_date(start_date)
        _gtfs_date(end_date)
        result[service_id] = CalendarRule(
            service_id=service_id,
            weekdays=weekdays,
            start_date=start_date,
            end_date=end_date,
        )
    return result


def _calendar_exceptions(rows: Iterable[dict[str, str]]) -> dict[tuple[str, str], int]:
    result = {}
    for row in rows:
        service_id = _required(row, "service_id", "calendar_dates.txt")
        value = _required(row, "date", "calendar_dates.txt")
        _gtfs_date(value)
        try:
            exception_type = int(_required(row, "exception_type", "calendar_dates.txt"))
        except ValueError as error:
            raise GTFSFeedError("invalid calendar exception type") from error
        if exception_type not in (1, 2):
            raise GTFSFeedError("invalid calendar exception type")
        key = (service_id, value)
        if key in result:
            raise GTFSFeedError("duplicate calendar exception")
        result[key] = exception_type
    return result


def _shapes(rows: Iterable[dict[str, str]]) -> dict[str, tuple[tuple[float, float], ...]]:
    pending: dict[str, list[tuple[int, float, float]]] = {}
    for row in rows:
        shape_id = _required(row, "shape_id", "shapes.txt")
        latitude = _float_field(row, "shape_pt_lat", "shapes.txt")
        longitude = _float_field(row, "shape_pt_lon", "shapes.txt")
        latitude, longitude = _coordinates(latitude, longitude)
        try:
            sequence = int(_required(row, "shape_pt_sequence", "shapes.txt"))
        except ValueError as error:
            raise GTFSFeedError("invalid shape sequence") from error
        pending.setdefault(shape_id, []).append((sequence, latitude, longitude))
    return {
        shape_id: tuple(
            (latitude, longitude)
            for _, latitude, longitude in sorted(points, key=lambda item: item[0])
        )
        for shape_id, points in pending.items()
    }


def _required(row: dict[str, str], field: str, table: str) -> str:
    value = row.get(field, "").strip()
    if not value:
        raise GTFSFeedError(f"missing {field} in {table}")
    return value


def _float_field(row: dict[str, str], field: str, table: str) -> float:
    try:
        return float(_required(row, field, table))
    except ValueError as error:
        raise GTFSFeedError(f"invalid {field} in {table}") from error


def _coordinates(latitude: float, longitude: float) -> tuple[float, float]:
    latitude = float(latitude)
    longitude = float(longitude)
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        raise GTFSFeedError("coordinates must be finite")
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        raise GTFSFeedError("coordinates outside valid range")
    return latitude, longitude


def _gtfs_date(value: str) -> date:
    normalized = value.replace("-", "")
    try:
        return datetime.strptime(normalized, "%Y%m%d").date()
    except ValueError as error:
        raise GTFSFeedError("invalid service date") from error


def _time_seconds(value: str) -> int:
    parts = value.split(":")
    if len(parts) != 3:
        raise GTFSFeedError("invalid GTFS time")
    try:
        hours, minutes, seconds = (int(part) for part in parts)
    except ValueError as error:
        raise GTFSFeedError("invalid GTFS time") from error
    if hours < 0 or not 0 <= minutes <= 59 or not 0 <= seconds <= 59:
        raise GTFSFeedError("invalid GTFS time")
    return hours * 3600 + minutes * 60 + seconds


def _bounded_limit(value: int, minimum: int, maximum: int) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise GTFSFeedError("limit must be an integer")
    if not minimum <= value <= maximum:
        raise GTFSFeedError(f"limit must be between {minimum} and {maximum}")
    return value


def _validate_member_name(name: str) -> None:
    normalized = name.replace("\\", "/")
    if not normalized or normalized.startswith("/"):
        raise GTFSFeedError("unsafe GTFS member path")
    parts = normalized.split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise GTFSFeedError("unsafe GTFS member path")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6_371_008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    return radius * 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _route_dict(route: Route) -> dict:
    return {
        "route_id": route.route_id,
        "short_name": route.short_name,
        "long_name": route.long_name,
        "route_type": route.route_type,
        "color": route.color,
        "text_color": route.text_color,
    }


def _stop_dict(stop: Stop) -> dict:
    return {
        "stop_id": stop.stop_id,
        "name": stop.name,
        "latitude": stop.latitude,
        "longitude": stop.longitude,
    }
