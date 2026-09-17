# zara-mobility

Provider-neutral maps, transit, rideshare handoffs, and trip-planning context for Zara.

The first slice is deliberately conservative: it builds validated handoffs and exposes verified provider profiles without pretending that opening an app booked a ride, that a schedule is realtime, or that Android live navigation exists when the bridge is absent.

## Tools

- `mobility.status`
- `mobility.search_places`
- `mobility.route`
- `mobility.show`
- `mobility.transit.profile`
- `mobility.rideshare.options`
- `mobility.rideshare.handoff`
- `mobility.trip_plan`
- `mobility.navigation.status`

## Google Maps

Google Maps search/directions/show handoffs use official Maps URLs with `api=1` and enforce a bounded generated URL. The base URL handoff does not require a Google Maps Platform API key.

`mobility.route` supports the closed travel modes `driving`, `walking`, `bicycling`, `transit`, and `two-wheeler`, plus the avoid values `tolls`, `highways`, and `ferries`.

## OpenStreetMap

The initial OpenStreetMap path supports web search and explicit-coordinate map handoff and always returns `© OpenStreetMap contributors` attribution metadata.

A future geocoder/routing adapter must respect the configured provider's policy. The public OSM Nominatim service is not a bulk/autocomplete backend, and the public OSRM demo must not be treated as production infrastructure. Configure a hosted or self-hosted endpoint before enabling sustained routing/geocoding traffic.

## Transit

`mobility.transit.profile` currently recognizes:

- `cota` — Central Ohio Transit Authority. The profile records COTA's public static GTFS plus GTFS-Realtime Trip Updates, Vehicle Positions, and Alerts endpoints. Parsing/live departure tools are a follow-on slice and are not falsely advertised by this first implementation.
- `gobus` — Ohio GoBus. The profile records schedule/catalog provenance and reports realtime as unavailable until a current verified realtime feed is configured.

GTFS/GTFS-RT parsing, stop/departure/vehicle/alert tools, and trip-event subscriptions remain tracked in `lost-rob0t/zara-plugins#829`.

## Uber and Lyft

Ride integrations are handoffs only. Zara never reports a ride as booked because an app/web URL launched.

Configure public developer client IDs in Zara's plugin configuration:

```toml
[plugins.zara-mobility]
uber_client_id = "..."
lyft_client_id = "..."
max_url_chars = 2048
# osm_routing_endpoint = "https://your-routing-service.example"
```

The first slice does not store provider secrets and does not fabricate fare or pickup ETA estimates. Those remain `unavailable` unless a future authenticated provider adapter supplies observed values.

## Android live navigation

True live route progress is owned by Zara Android issue `lost-rob0t/zara#1017`. The intended implementation uses a typed optional Google Navigation SDK bridge rather than scraping the Google Maps application through Accessibility.

Until that bridge is connected, `mobility.navigation.status` returns an explicit unavailable state.

## Safety and authority

- no raw caller-provided Android Intent action/package/component;
- no automatic rideshare payment/booking;
- no fabricated live traffic, ETA, fare, bus position, or route state;
- URL, text, coordinate, stop, mode, and provider inputs are bounded/validated;
- provider tokens/API keys must never be committed or logged;
- trip/navigation observations are data, not authority for arbitrary device actions.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-mobility/test -t plugins/zara-mobility/test
python3 scripts/validate-registry.py
nix flake check
```

Tracking: `lost-rob0t/zara-plugins#829`, Android bridge `lost-rob0t/zara#1017`.
