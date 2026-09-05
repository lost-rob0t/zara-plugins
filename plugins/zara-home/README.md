# zara-home

`zara-home` provides a provider-neutral smart-home domain for Zara. Providers expose normalized rooms, devices, capabilities, observed state, scenes, presence, and environmental observations; public Zara tools do not depend on Home Assistant or SmartThings wire formats.

## Safety model

Writes are validated against the device capability schema before a provider call. Enum membership and numeric ranges are enforced. Capabilities marked `security_sensitive` are refused by the generic mutation path, so vague intent cannot unlock/open security-sensitive devices. Provider acceptance alone is not reported as success: device writes are re-read and return explicit `verified` state plus the original provider evidence.

The default plugin has no configured provider and reports `smart-home-provider-not-configured` instead of fabricating device state or successful actions. Real provider adapters remain explicit configuration/integration work; tests use fake adapters only and require no network.

## Facts and planning

`home.room.state` returns one normalized room snapshot with device, presence, and environment data. `home.plan` is deliberately non-mutating. The initial deterministic rule surface accepts only `make the <room> comfortable`, projects explicit facts such as `occupied(office)` and `temperature_c(office,18.0)`, and returns proposed actions with stable rule IDs plus a human-readable reason. Unknown high-level intents fail instead of being guessed.

This keeps planning separate from execution: proposed actions still have to pass `home.device.set` capability/range/security validation and post-write verification. The same normalized facts and rule identifiers are suitable for projection into `zara-expert` once Zara exposes a canonical cross-plugin service lookup; `zara-home` does not instantiate a second expert runtime to fake that integration.

## Tests

```sh
python3 -m unittest discover -s plugins/zara-home/test -t plugins/zara-home/test
python3 scripts/validate-registry.py
nix flake check
```
