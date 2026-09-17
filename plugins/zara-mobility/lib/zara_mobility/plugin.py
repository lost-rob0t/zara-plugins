from __future__ import annotations

import json
from collections.abc import Mapping

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import MobilityDomain, MobilityError


PLUGIN_VERSION = "0.1.0"


class ZaraMobilityPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-mobility",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Provider-neutral maps, transit, rideshare handoffs, and trip-planning context",
    )

    def __init__(self) -> None:
        self.domain = MobilityDomain()

    def start(self, runtime) -> None:
        section = self._section(runtime.configuration)
        self.domain = MobilityDomain(
            uber_client_id=self._optional_string(section.get("uber_client_id"), "uber_client_id"),
            lyft_client_id=self._optional_string(section.get("lyft_client_id"), "lyft_client_id"),
            osm_routing_endpoint=self._optional_string(
                section.get("osm_routing_endpoint"),
                "osm_routing_endpoint",
            ),
            max_url_chars=self._max_url_chars(section.get("max_url_chars", 2048)),
        )

    def stop(self) -> None:
        return None

    def status(self) -> str:
        return self._json(
            {
                "status": "ready",
                "maps": ["google_maps", "openstreetmap"],
                "transit_profiles": ["cota", "gobus"],
                "rideshare": self.domain.rideshare_options(),
                "navigation": self.domain.navigation_status(),
                "live_transit_parsing": "follow_on",
            }
        )

    def search_places(self, query: str, provider: str = "auto") -> str:
        return self._json(self.domain.search_places(query, provider))

    def route(
        self,
        destination: str,
        origin: str = "",
        travel_mode: str = "driving",
        waypoints: list[str] | None = None,
        avoid: list[str] | None = None,
        provider: str = "auto",
    ) -> str:
        return self._json(
            self.domain.route(
                destination=destination,
                origin=origin,
                travel_mode=travel_mode,
                waypoints=waypoints,
                avoid=avoid,
                provider=provider,
            )
        )

    def show(
        self,
        location: str = "",
        latitude: float | None = None,
        longitude: float | None = None,
        zoom: int = 15,
        provider: str = "auto",
    ) -> str:
        selected = provider.strip().lower() if isinstance(provider, str) else provider
        if selected in {"auto", "google_maps"}:
            if not location:
                raise MobilityError("location is required for Google Maps show")
            return self._json(self.domain.google_show(location))
        if selected == "openstreetmap":
            if latitude is None or longitude is None:
                raise MobilityError("latitude and longitude are required for OpenStreetMap show")
            return self._json(self.domain.osm_show(latitude, longitude, zoom))
        raise MobilityError("unsupported mobility provider")

    def transit_profile(self, agency: str) -> str:
        return self._json(self.domain.transit_profile(agency))

    def rideshare_options(self) -> str:
        return self._json(self.domain.rideshare_options())

    def rideshare_handoff(
        self,
        provider: str,
        destination: dict,
        pickup: dict | None = None,
        product: str = "",
    ) -> str:
        return self._json(
            self.domain.rideshare_handoff(
                provider,
                destination=destination,
                pickup=pickup,
                product=product,
            )
        )

    def trip_plan(
        self,
        stops: list[str],
        origin: str = "",
        travel_mode: str = "driving",
        provider: str = "auto",
    ) -> str:
        return self._json(
            self.domain.trip_plan(
                stops=stops,
                origin=origin,
                travel_mode=travel_mode,
                provider=provider,
            )
        )

    def navigation_status(self) -> str:
        return self._json(self.domain.navigation_status())

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.status,
                name="mobility.status",
                description="Report configured map, transit, rideshare, and live-navigation capabilities without guessing unavailable providers.",
            ),
            StructuredTool.from_function(
                func=self.search_places,
                name="mobility.search_places",
                description="Build a bounded Google Maps or OpenStreetMap place-search handoff. This does not claim a place was visited or selected.",
            ),
            StructuredTool.from_function(
                func=self.route,
                name="mobility.route",
                description="Build a bounded route handoff. Google Maps works keylessly; OpenStreetMap routing requires an explicit routing backend.",
            ),
            StructuredTool.from_function(
                func=self.show,
                name="mobility.show",
                description="Build a map handoff for a named Google Maps location or explicit OpenStreetMap coordinates.",
            ),
            StructuredTool.from_function(
                func=self.transit_profile,
                name="mobility.transit.profile",
                description="Describe verified transit data sources for COTA or GoBus and truthfully report realtime availability.",
            ),
            StructuredTool.from_function(
                func=self.rideshare_options,
                name="mobility.rideshare.options",
                description="Report Uber and Lyft handoff availability. Fare and ETA estimates remain unavailable unless a future verified API backend supplies them.",
            ),
            StructuredTool.from_function(
                func=self.rideshare_handoff,
                name="mobility.rideshare.handoff",
                description="Prepare an Uber or Lyft ride-request handoff with validated coordinates. The user must confirm booking in the provider UI.",
            ),
            StructuredTool.from_function(
                func=self.trip_plan,
                name="mobility.trip_plan",
                description="Prepare a bounded read-only multi-stop trip plan and provider handoff; it performs no navigation or booking side effect.",
            ),
            StructuredTool.from_function(
                func=self.navigation_status,
                name="mobility.navigation.status",
                description="Report whether the optional Android live Navigation SDK bridge is actually connected.",
            ),
        )

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _section(configuration: object) -> Mapping[str, object]:
        if not isinstance(configuration, Mapping):
            return {}
        plugins = configuration.get("plugins", {})
        if not isinstance(plugins, Mapping):
            return {}
        section = plugins.get("zara-mobility", {})
        return section if isinstance(section, Mapping) else {}

    @staticmethod
    def _optional_string(value: object, name: str) -> str | None:
        if value in (None, ""):
            return None
        if not isinstance(value, str):
            raise MobilityError(f"{name} must be a string")
        return value

    @staticmethod
    def _max_url_chars(value: object) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise MobilityError("max_url_chars must be an integer")
        return value


def create_plugin():
    return ZaraMobilityPlugin()
