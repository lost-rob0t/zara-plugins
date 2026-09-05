# zara-home

`zara-home` provides a provider-neutral smart-home domain for Zara. Providers expose normalized rooms, devices, capabilities, observed state, scenes, presence, and environmental observations; public Zara tools do not depend on Home Assistant or SmartThings wire formats.

## Safety model

Writes are validated against the device capability schema before a provider call. Enum membership and numeric ranges are enforced. Capabilities marked `security_sensitive` are refused by the generic mutation path, so vague intent cannot unlock/open security-sensitive devices. Provider acceptance alone is not reported as success: device writes are re-read and return explicit `verified` state plus the original provider evidence.

The default plugin has no configured provider and reports `smart-home-provider-not-configured` instead of fabricating device state or successful actions. Real provider adapters remain explicit configuration/integration work; tests use fake adapters only and require no network.

## Expert integration

The normalized domain is suitable for projecting room/device/state observations into `zara-expert` rules for higher-level plans such as comfort, lighting, and climate. Expert reasoning may propose operations, but mutations still pass through the capability validator and provider verification path.

## Tests

```sh
python3 -m unittest discover -s plugins/zara-home/test -t plugins/zara-home/test
python3 scripts/validate-registry.py
nix flake check
```
