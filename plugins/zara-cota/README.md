# zara-cota

`zara-cota` is Zara's COTA transit integration for Columbus/Central Ohio.

Implementation tracker: [zara-plugins#830](https://github.com/lost-rob0t/zara-plugins/issues/830)

Shared OpenStreetMap/maps and destination-discovery contract: [zara#1016](https://github.com/lost-rob0t/zara/issues/1016)

## Current slice

Version `0.1.0` implements the first desktop/shared slice:

- bounded static GTFS ZIP/CSV decoding;
- routes, stops, trips, service calendars, stop times and shapes;
- nearby-stop queries using explicit supplied coordinates;
- scheduled departure queries with explicit `departure_source = scheduled`;
- route geometry for the shared Zara Maps renderer;
- atomic replacement of a last-good in-memory static snapshot;
- bounded HTTPS/loopback-HTTP feed fetching with an identifying User-Agent.

The default static feed is COTA's published GTFS archive:

`https://www.cota.com/data/cota.gtfs.zip`

The feed URL is configurable and is intentionally not part of the tool schema.

## Not implemented yet

The following remain tracked by #830 and are deliberately reported as unavailable rather than faked:

- GTFS-Realtime trip updates;
- GTFS-Realtime vehicle positions;
- GTFS-Realtime alerts;
- realtime-adjusted arrivals/departures;
- canonical Prolog observed-fact projection;
- common-destination resolution through Zara#1016;
- deterministic journey planning;
- final Zara Maps feature projection;
- Android `ai.zara.cota` APK / `ZARA-ANDROID-PLUGIN/1` adapter.

Android production IPC remains gated by Zara's Android plugin-host architecture (#924). The shared GTFS domain is intended to be reused by the Android implementation rather than reimplemented there.

## Tools

The plugin currently exposes:

- `cota.status`
- `cota.refresh_static`
- `cota.routes`
- `cota.route`
- `cota.stop`
- `cota.route_stops`
- `cota.stops_near`
- `cota.departures`
- `cota.route_geometry`

`cota.stops_near` does **not** read device or desktop location. Zara must supply coordinates after the normal capability/policy path authorizes a location or resolves a trusted destination.

`cota.route_geometry` returns normalized coordinates only. It does not render a map and has no Google Maps dependency. Zara#1016 owns rendering and makes OpenStreetMap the first-class map tier.

## Configuration

Service-plugin configuration is read through Zara's normal plugin configuration boundary. Supported keys in this slice:

```text
static_feed_url
request_timeout_seconds
max_response_bytes
```

Defaults:

```text
static_feed_url = https://www.cota.com/data/cota.gtfs.zip
request_timeout_seconds = 10
max_response_bytes = 16777216
```

Remote feed URLs must use HTTPS. Loopback HTTP is allowed for local fixtures/self-hosted development.

## Data and attribution

COTA publishes static GTFS and realtime feeds at <https://www.cota.com/data/> under COTA's current data terms. Those terms are revocable and the data is provided as-is/as-available. This plugin does not bundle COTA logos or claim endorsement.

Map rendering/attribution belongs to Zara Maps. OpenStreetMap data and public infrastructure must be used according to OSMF attribution and service usage policies.

## Tests

```sh
python3 -m unittest discover -s plugins/zara-cota/test -t plugins/zara-cota/test
python3 scripts/validate-registry.py
nix flake check
```

Tests are network-free and build deterministic GTFS fixture archives in memory.
