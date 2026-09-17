from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from typing import Mapping

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .gtfs import FeedLimits, GTFSFeedError, StaticSnapshot, load_static_gtfs


PLUGIN_VERSION = "0.1.0"
DEFAULT_STATIC_FEED_URL = "https://www.cota.com/data/cota.gtfs.zip"
DEFAULT_TIMEOUT_SECONDS = 10.0
DEFAULT_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
USER_AGENT = "Zara-COTA/0.1 (+https://github.com/lost-rob0t/zara-plugins)"


class CotaTransportError(RuntimeError):
    pass


class BoundedHttpFetcher:
    def __init__(
        self,
        *,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        opener=None,
    ) -> None:
        timeout_seconds = float(timeout_seconds)
        if not 0.1 <= timeout_seconds <= 60.0:
            raise ValueError("timeout_seconds must be between 0.1 and 60")
        if not 1024 <= int(max_response_bytes) <= 64 * 1024 * 1024:
            raise ValueError("max_response_bytes must be between 1024 and 67108864")
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = int(max_response_bytes)
        self.opener = opener or urllib.request.urlopen

    def fetch(self, url: str) -> bytes:
        _validate_feed_url(url)
        request = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": USER_AGENT, "Accept": "application/zip"},
        )
        try:
            response = self.opener(request, timeout=self.timeout_seconds)
            try:
                declared = response.headers.get("Content-Length")
                if declared is not None and int(declared) > self.max_response_bytes:
                    raise CotaTransportError("COTA response exceeded size limit")
                payload = response.read(self.max_response_bytes + 1)
            finally:
                response.close()
        except CotaTransportError:
            raise
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, ValueError):
            raise CotaTransportError("COTA feed request failed") from None
        if len(payload) > self.max_response_bytes:
            raise CotaTransportError("COTA response exceeded size limit")
        return payload


class ZaraCotaPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-cota",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Bounded COTA static GTFS transit queries with explicit schedule provenance",
    )

    def __init__(self, *, fetcher=None) -> None:
        self._fetcher = fetcher or BoundedHttpFetcher()
        self._source_url = DEFAULT_STATIC_FEED_URL
        self._snapshot: StaticSnapshot | None = None
        self._lock = threading.RLock()

    def start(self, runtime) -> None:
        configuration: Mapping = runtime.configuration
        source_url = str(configuration.get("static_feed_url", DEFAULT_STATIC_FEED_URL))
        _validate_feed_url(source_url)
        timeout = float(configuration.get("request_timeout_seconds", DEFAULT_TIMEOUT_SECONDS))
        max_bytes = int(configuration.get("max_response_bytes", DEFAULT_MAX_RESPONSE_BYTES))
        if isinstance(self._fetcher, BoundedHttpFetcher):
            self._fetcher = BoundedHttpFetcher(
                timeout_seconds=timeout,
                max_response_bytes=max_bytes,
            )
        self._source_url = source_url

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        with self._lock:
            snapshot = self._snapshot
        if snapshot is None:
            return self._json(
                {
                    "status": "degraded",
                    "static_feed": "not_loaded",
                    "realtime": "not_implemented",
                }
            )
        return self._json(
            {
                "status": "ready_static",
                "static_feed": "ready",
                "static_generation": snapshot.generation,
                "route_count": len(snapshot.routes),
                "stop_count": len(snapshot.stops),
                "trip_count": len(snapshot.trips),
                "realtime": "not_implemented",
            }
        )

    def refresh_static(self) -> str:
        payload = self._fetcher.fetch(self._source_url)
        snapshot = load_static_gtfs(
            payload,
            source="cota_gtfs_static",
            limits=FeedLimits(max_archive_bytes=self._fetcher.max_response_bytes)
            if isinstance(self._fetcher, BoundedHttpFetcher)
            else None,
        )
        with self._lock:
            self._snapshot = snapshot
        return self._json(
            {
                "status": "refreshed",
                "static_generation": snapshot.generation,
                "route_count": len(snapshot.routes),
                "stop_count": len(snapshot.stops),
                "trip_count": len(snapshot.trips),
            }
        )

    def routes(self, limit: int = 100) -> str:
        snapshot = self._require_snapshot()
        return self._json(
            {
                "status": "ready",
                "static_generation": snapshot.generation,
                "routes": snapshot.route_list(limit=limit),
            }
        )

    def route(self, route_id: str) -> str:
        snapshot = self._require_snapshot()
        return self._json(
            {
                "status": "ready",
                "static_generation": snapshot.generation,
                "route": snapshot.route(route_id),
            }
        )

    def stop_info(self, stop_id: str) -> str:
        snapshot = self._require_snapshot()
        return self._json(
            {
                "status": "ready",
                "static_generation": snapshot.generation,
                "stop": snapshot.stop(stop_id),
            }
        )

    def route_stops(
        self,
        route_id: str,
        direction_id: str = "",
        limit: int = 500,
    ) -> str:
        snapshot = self._require_snapshot()
        return self._json(
            {
                "status": "ready",
                "static_generation": snapshot.generation,
                "route_id": route_id,
                "direction_id": direction_id,
                "stops": snapshot.route_stops(
                    route_id,
                    direction_id=direction_id,
                    limit=limit,
                ),
            }
        )

    def stops_near(
        self,
        latitude: float,
        longitude: float,
        radius_m: float = 1000.0,
        limit: int = 20,
    ) -> str:
        snapshot = self._require_snapshot()
        return self._json(
            {
                "status": "ready",
                "static_generation": snapshot.generation,
                "stops": snapshot.stops_near(
                    latitude,
                    longitude,
                    radius_m=radius_m,
                    limit=limit,
                ),
            }
        )

    def departures(
        self,
        stop_id: str,
        service_date: str,
        after_time: str = "00:00:00",
        limit: int = 20,
    ) -> str:
        snapshot = self._require_snapshot()
        return self._json(
            {
                "status": "ready_scheduled",
                "static_generation": snapshot.generation,
                "realtime_applied": False,
                "departures": snapshot.departures(
                    stop_id,
                    service_date,
                    after_time=after_time,
                    limit=limit,
                ),
            }
        )

    def route_geometry(self, route_id: str, direction_id: str = "") -> str:
        snapshot = self._require_snapshot()
        return self._json(
            {
                "status": "ready",
                "static_generation": snapshot.generation,
                "geometry": snapshot.route_geometry(
                    route_id,
                    direction_id=direction_id,
                ),
            }
        )

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.status,
                name="cota.status",
                description="Report COTA static/realtime feed readiness without fetching location.",
            ),
            StructuredTool.from_function(
                func=self.refresh_static,
                name="cota.refresh_static",
                description="Refresh the bounded official COTA static GTFS snapshot atomically.",
            ),
            StructuredTool.from_function(
                func=self.routes,
                name="cota.routes",
                description="List bounded COTA routes from the loaded static GTFS generation.",
            ),
            StructuredTool.from_function(
                func=self.route,
                name="cota.route",
                description="Read one COTA route by exact GTFS route_id.",
            ),
            StructuredTool.from_function(
                func=self.stop_info,
                name="cota.stop",
                description="Read one COTA stop by exact GTFS stop_id.",
            ),
            StructuredTool.from_function(
                func=self.route_stops,
                name="cota.route_stops",
                description="List bounded stops served by a COTA route and optional direction.",
            ),
            StructuredTool.from_function(
                func=self.stops_near,
                name="cota.stops_near",
                description="Find COTA stops near explicit approved coordinates; this tool never reads device location itself.",
            ),
            StructuredTool.from_function(
                func=self.departures,
                name="cota.departures",
                description="List scheduled COTA departures and label them as scheduled until realtime is available.",
            ),
            StructuredTool.from_function(
                func=self.route_geometry,
                name="cota.route_geometry",
                description="Return GTFS route geometry for Zara Maps rendering; this tool does not render a map.",
            ),
        )

    def _require_snapshot(self) -> StaticSnapshot:
        with self._lock:
            snapshot = self._snapshot
        if snapshot is None:
            raise GTFSFeedError("COTA static feed is not loaded; call cota.refresh_static first")
        return snapshot


def _validate_feed_url(url: str) -> None:
    if not isinstance(url, str) or not 1 <= len(url) <= 2048:
        raise ValueError("feed URL length is invalid")
    parsed = urllib.parse.urlsplit(url)
    if parsed.username or parsed.password or parsed.fragment:
        raise ValueError("feed URL contains unsupported authority or fragment")
    if parsed.scheme == "https" and parsed.netloc:
        return
    if parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}:
        return
    raise ValueError("feed URL must use HTTPS or loopback HTTP")


def create_plugin():
    return ZaraCotaPlugin()
