from __future__ import annotations

import json
import math
from collections.abc import Mapping, Sequence
from urllib.parse import quote, urlencode


class MobilityError(ValueError):
    pass


class MobilityDomain:
    GOOGLE_BASE = "https://www.google.com/maps"
    OSM_BASE = "https://www.openstreetmap.org"
    OSM_ATTRIBUTION = "© OpenStreetMap contributors"
    GOOGLE_MODES = frozenset({"driving", "walking", "bicycling", "transit", "two-wheeler"})
    GOOGLE_AVOID = frozenset({"tolls", "highways", "ferries"})
    RIDESHARE_PROVIDERS = frozenset({"uber", "lyft"})

    def __init__(
        self,
        *,
        uber_client_id: str | None = None,
        lyft_client_id: str | None = None,
        osm_routing_endpoint: str | None = None,
        max_url_chars: int = 2048,
    ) -> None:
        if not isinstance(max_url_chars, int) or max_url_chars < 128 or max_url_chars > 8192:
            raise MobilityError("max_url_chars is outside supported bounds")
        self.max_url_chars = max_url_chars
        self.uber_client_id = self._optional_identifier(uber_client_id, "Uber client ID")
        self.lyft_client_id = self._optional_identifier(lyft_client_id, "Lyft client ID")
        self.osm_routing_endpoint = self._optional_https_url(osm_routing_endpoint, "OSM routing endpoint")

    def google_search(self, query: str) -> dict:
        clean = self._text(query, "query")
        url = self._url(f"{self.GOOGLE_BASE}/search/", {"api": "1", "query": clean})
        return {
            "status": "handoff_ready",
            "provider": "google_maps",
            "action": "search",
            "url": url,
            "side_effect_performed": False,
        }

    def google_show(self, location: str) -> dict:
        result = self.google_search(location)
        result["action"] = "show"
        return result

    def google_directions(
        self,
        destination: str,
        origin: str = "",
        travel_mode: str = "driving",
        waypoints: Sequence[str] | None = None,
        avoid: Sequence[str] | None = None,
    ) -> dict:
        mode = self._enum(travel_mode, self.GOOGLE_MODES, "travel mode")
        target = self._text(destination, "destination")
        source = self._optional_text(origin, "origin")
        stops = self._text_list(waypoints or (), "waypoints", max_items=3)
        avoid_values = self._enum_list(avoid or (), self.GOOGLE_AVOID, "avoid", max_items=3)
        params: dict[str, str] = {"api": "1", "destination": target, "travelmode": mode}
        if source:
            params["origin"] = source
        if stops:
            params["waypoints"] = "|".join(stops)
        if avoid_values:
            params["avoid"] = "|".join(avoid_values)
        url = self._url(f"{self.GOOGLE_BASE}/dir/", params)
        return {
            "status": "handoff_ready",
            "provider": "google_maps",
            "action": "directions",
            "travel_mode": mode,
            "waypoints": stops,
            "url": url,
            "side_effect_performed": False,
        }

    def osm_search(self, query: str) -> dict:
        clean = self._text(query, "query")
        url = self._url(f"{self.OSM_BASE}/search", {"query": clean})
        return {
            "status": "handoff_ready",
            "provider": "openstreetmap",
            "action": "search",
            "url": url,
            "attribution": self.OSM_ATTRIBUTION,
            "service_class": "public-web-handoff",
            "side_effect_performed": False,
        }

    def osm_show(self, latitude: float, longitude: float, zoom: int = 15) -> dict:
        lat = self._coordinate(latitude, "latitude", -90.0, 90.0)
        lon = self._coordinate(longitude, "longitude", -180.0, 180.0)
        if not isinstance(zoom, int) or isinstance(zoom, bool) or not 0 <= zoom <= 19:
            raise MobilityError("zoom must be an integer from 0 to 19")
        lat_text = self._number_text(lat)
        lon_text = self._number_text(lon)
        base = self._url(f"{self.OSM_BASE}/", {"mlat": lat_text, "mlon": lon_text})
        url = self._bounded_url(f"{base}#map={zoom}/{lat_text}/{lon_text}")
        return {
            "status": "handoff_ready",
            "provider": "openstreetmap",
            "action": "show",
            "url": url,
            "attribution": self.OSM_ATTRIBUTION,
            "service_class": "public-web-handoff",
            "side_effect_performed": False,
        }

    def search_places(self, query: str, provider: str = "auto") -> dict:
        selected = self._provider(provider, {"auto", "google_maps", "openstreetmap"})
        if selected in {"auto", "google_maps"}:
            return self.google_search(query)
        return self.osm_search(query)

    def route(
        self,
        destination: str,
        origin: str = "",
        travel_mode: str = "driving",
        waypoints: Sequence[str] | None = None,
        avoid: Sequence[str] | None = None,
        provider: str = "auto",
    ) -> dict:
        selected = self._provider(provider, {"auto", "google_maps", "openstreetmap"})
        if selected in {"auto", "google_maps"}:
            return self.google_directions(destination, origin, travel_mode, waypoints, avoid)
        if not self.osm_routing_endpoint:
            return {
                "status": "config_required",
                "provider": "openstreetmap",
                "action": "directions",
                "reason": "osm-routing-endpoint-not-configured",
                "attribution": self.OSM_ATTRIBUTION,
                "side_effect_performed": False,
            }
        return {
            "status": "unsupported",
            "provider": "openstreetmap",
            "action": "directions",
            "reason": "coordinate-routing-adapter-not-enabled-in-initial-slice",
            "routing_endpoint": self.osm_routing_endpoint,
            "attribution": self.OSM_ATTRIBUTION,
            "side_effect_performed": False,
        }

    def transit_profile(self, agency: str) -> dict:
        key = self._text(agency, "agency", max_chars=64).lower().replace("-", "").replace("_", "").replace(" ", "")
        if key in {"cota", "centralohiotransitauthority"}:
            return {
                "agency": "cota",
                "name": "Central Ohio Transit Authority",
                "region": "Columbus, Ohio",
                "realtime": True,
                "feeds": {
                    "static": "https://www.cota.com/data/cota.gtfs.zip",
                    "trip_updates": "https://gtfs-rt.cota.vontascloud.com/TMGTFSRealTimeWebService/TripUpdate/TripUpdates.pb",
                    "vehicle_positions": "https://gtfs-rt.cota.vontascloud.com/TMGTFSRealTimeWebService/Vehicle/VehiclePositions.pb",
                    "alerts": "https://gtfs-rt.cota.vontascloud.com/TMGTFSRealTimeWebService/Alert/Alerts.pb",
                },
                "status": "profile_ready",
                "live_data_parsing": "follow_on",
            }
        if key in {"gobus", "ohiogobus"}:
            return {
                "agency": "gobus",
                "name": "GoBus",
                "region": "Ohio",
                "website": "https://ridegobus.com/",
                "realtime": False,
                "schedule_source": "transitland:f-utel~uiuc~intercity~bus",
                "catalog_url": "https://www.transit.land/feeds/f-utel~uiuc~intercity~bus",
                "status": "schedule_profile_ready",
                "realtime_reason": "no-current-verified-realtime-feed-configured",
            }
        raise MobilityError("unknown transit agency")

    def rideshare_options(self) -> list[dict]:
        return [
            {
                "provider": "uber",
                "handoff_available": bool(self.uber_client_id),
                "status": "ready" if self.uber_client_id else "config_required",
                "estimates": "unavailable",
                "booking": "user_confirmed_in_provider",
            },
            {
                "provider": "lyft",
                "handoff_available": bool(self.lyft_client_id),
                "status": "ready" if self.lyft_client_id else "config_required",
                "estimates": "unavailable",
                "booking": "user_confirmed_in_provider",
            },
        ]

    def rideshare_handoff(
        self,
        provider: str,
        *,
        destination: Mapping[str, object],
        pickup: Mapping[str, object] | None = None,
        product: str = "",
    ) -> dict:
        selected = self._provider(provider, self.RIDESHARE_PROVIDERS)
        target = self._location(destination, "destination")
        source = None if pickup is None else self._location(pickup, "pickup")
        product_name = self._optional_text(product, "product", max_chars=64)
        if selected == "uber":
            return self._uber_handoff(source, target, product_name)
        return self._lyft_handoff(source, target, product_name)

    def trip_plan(
        self,
        stops: Sequence[str],
        origin: str = "",
        travel_mode: str = "driving",
        provider: str = "auto",
    ) -> dict:
        values = self._text_list(stops, "stops", max_items=4)
        if not values:
            raise MobilityError("stops must contain at least one destination")
        selected = self._provider(provider, {"auto", "google_maps", "openstreetmap"})
        if selected == "openstreetmap":
            return {
                "status": "config_required",
                "provider": "openstreetmap",
                "reason": "osm-trip-routing-requires-coordinate-routing-provider",
                "stops": values,
                "side_effect_performed": False,
            }
        handoff = self.google_directions(
            destination=values[-1],
            origin=origin,
            travel_mode=travel_mode,
            waypoints=values[:-1],
        )
        return {
            "status": "plan_ready",
            "provider": "google_maps",
            "stops": values,
            "handoff": handoff,
            "side_effect_performed": False,
        }

    def navigation_status(self) -> dict:
        return {
            "available": False,
            "provider": "google_navigation_sdk",
            "reason": "android-navigation-bridge-not-connected",
            "live": False,
        }

    def _uber_handoff(
        self,
        pickup: dict[str, object] | None,
        destination: dict[str, object],
        product: str,
    ) -> dict:
        if not self.uber_client_id:
            return self._rideshare_config_required("uber")
        params: dict[str, str] = {
            "client_id": self.uber_client_id,
            "pickup": "my_location" if pickup is None else self._compact_json(self._uber_location(pickup)),
            "drop[0]": self._compact_json(self._uber_location(destination)),
        }
        if product:
            params["product_id"] = product
        url = self._url("https://m.uber.com/looking", params)
        return self._rideshare_ready("uber", url)

    def _lyft_handoff(
        self,
        pickup: dict[str, object] | None,
        destination: dict[str, object],
        product: str,
    ) -> dict:
        if not self.lyft_client_id:
            return self._rideshare_config_required("lyft")
        params = {
            "partner": self.lyft_client_id,
            "id": product or "lyft",
            "destination[latitude]": self._number_text(destination["latitude"]),
            "destination[longitude]": self._number_text(destination["longitude"]),
        }
        if pickup is not None:
            params["pickup[latitude]"] = self._number_text(pickup["latitude"])
            params["pickup[longitude]"] = self._number_text(pickup["longitude"])
        url = self._url("https://ride.lyft.com/u", params)
        return self._rideshare_ready("lyft", url)

    @staticmethod
    def _rideshare_ready(provider: str, url: str) -> dict:
        return {
            "status": "handoff_ready",
            "provider": provider,
            "url": url,
            "booking_confirmed": False,
            "user_confirmation_required": True,
            "side_effect_performed": False,
        }

    @staticmethod
    def _rideshare_config_required(provider: str) -> dict:
        return {
            "status": "config_required",
            "provider": provider,
            "reason": f"{provider}-client-id-not-configured",
            "booking_confirmed": False,
            "user_confirmation_required": True,
            "side_effect_performed": False,
        }

    def _location(self, value: Mapping[str, object], label: str) -> dict[str, object]:
        if not isinstance(value, Mapping):
            raise MobilityError(f"{label} must be an object")
        allowed = {"latitude", "longitude", "nickname", "address"}
        unknown = set(value) - allowed
        if unknown:
            raise MobilityError(f"{label} contains unsupported fields")
        if "latitude" not in value or "longitude" not in value:
            raise MobilityError(f"{label} requires latitude and longitude")
        result: dict[str, object] = {
            "latitude": self._coordinate(value["latitude"], f"{label} latitude", -90.0, 90.0),
            "longitude": self._coordinate(value["longitude"], f"{label} longitude", -180.0, 180.0),
        }
        nickname = self._optional_text(value.get("nickname", ""), f"{label} nickname", max_chars=128)
        address = self._optional_text(value.get("address", ""), f"{label} address", max_chars=256)
        if nickname:
            result["nickname"] = nickname
        if address:
            result["address"] = address
        return result

    @staticmethod
    def _uber_location(value: Mapping[str, object]) -> dict[str, object]:
        result: dict[str, object] = {
            "latitude": value["latitude"],
            "longitude": value["longitude"],
        }
        if "nickname" in value:
            result["addressLine1"] = value["nickname"]
        if "address" in value:
            result["addressLine2"] = value["address"]
        return result

    @staticmethod
    def _compact_json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    def _url(self, base: str, params: Mapping[str, object]) -> str:
        query = urlencode(params, quote_via=quote, safe="")
        return self._bounded_url(f"{base}?{query}")

    def _bounded_url(self, url: str) -> str:
        if len(url) > self.max_url_chars:
            raise MobilityError("generated URL is too long")
        return url

    @staticmethod
    def _provider(value: str, allowed: set[str] | frozenset[str]) -> str:
        if not isinstance(value, str):
            raise MobilityError("provider must be a string")
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise MobilityError("unsupported mobility provider")
        return normalized

    def _text_list(self, values: Sequence[str], label: str, *, max_items: int) -> list[str]:
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise MobilityError(f"{label} must be a list")
        if len(values) > max_items:
            raise MobilityError(f"{label} contains too many items")
        return [self._text(value, f"{label} item") for value in values]

    @staticmethod
    def _enum(value: str, allowed: frozenset[str], label: str) -> str:
        if not isinstance(value, str):
            raise MobilityError(f"{label} must be a string")
        normalized = value.strip().lower()
        if normalized not in allowed:
            raise MobilityError(f"unsupported {label}")
        return normalized

    def _enum_list(
        self,
        values: Sequence[str],
        allowed: frozenset[str],
        label: str,
        *,
        max_items: int,
    ) -> list[str]:
        if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
            raise MobilityError(f"{label} must be a list")
        if len(values) > max_items:
            raise MobilityError(f"{label} contains too many items")
        normalized = [self._enum(value, allowed, label) for value in values]
        if len(set(normalized)) != len(normalized):
            raise MobilityError(f"{label} contains duplicate values")
        return normalized

    @staticmethod
    def _coordinate(value: object, label: str, minimum: float, maximum: float) -> float:
        if isinstance(value, bool):
            raise MobilityError(f"{label} must be numeric")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise MobilityError(f"{label} must be numeric") from error
        if not math.isfinite(number) or not minimum <= number <= maximum:
            raise MobilityError(f"{label} is outside valid bounds")
        return number

    @staticmethod
    def _number_text(value: object) -> str:
        number = float(value)
        return format(number, ".10g")

    def _optional_identifier(self, value: str | None, label: str) -> str | None:
        if value is None:
            return None
        return self._text(value, label, max_chars=256)

    def _optional_https_url(self, value: str | None, label: str) -> str | None:
        if value is None:
            return None
        cleaned = self._text(value, label, max_chars=1024)
        if not cleaned.startswith("https://"):
            raise MobilityError(f"{label} must use https")
        return cleaned.rstrip("/")

    def _optional_text(self, value: object, label: str, *, max_chars: int = 512) -> str:
        if value in (None, ""):
            return ""
        return self._text(value, label, max_chars=max_chars)

    @staticmethod
    def _text(value: object, label: str, *, max_chars: int = 512) -> str:
        if not isinstance(value, str):
            raise MobilityError(f"{label} must be a string")
        cleaned = value.strip()
        if not cleaned:
            raise MobilityError(f"{label} must not be blank")
        if len(cleaned) > max_chars:
            raise MobilityError(f"{label} is too long")
        if any(ord(char) < 0x20 for char in cleaned):
            raise MobilityError(f"{label} contains control characters")
        return cleaned
