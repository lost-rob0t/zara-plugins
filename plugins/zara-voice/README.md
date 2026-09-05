# zara-voice

`zara-voice` is Zara's provider-neutral runtime speech synthesis and playback service. It owns normal TTS/profile selection only; voice cloning, training, dataset construction, and model creation belong in `zara-voice-lab`.

The public domain keeps backend-specific SDKs behind adapters. A configured backend reports only normalized capability metadata: locality (`local` or `remote`), languages, styles, emotions, streaming support, and bounded voice profiles. Credentials and provider-private configuration are never returned through the tool surface or stored in the registry/Nix store.

## Tools

- `voice.status`
- `voice.backends`
- `voice.profiles`
- `voice.synthesize`
- `voice.play`
- `voice.cancel`

Synthesis requires an explicit backend and profile. Text and output duration are bounded. Language/profile compatibility is validated before provider work; style and emotion are accepted only when the selected backend advertises those capabilities.

Remote synthesis is **off by default**. Operators must explicitly set `allow_remote = true` in the plugin configuration before text may be sent to a remote TTS adapter. Local backends remain first-class and require no network semantics in the public API.

Playback and cancellation do not claim success from an adapter acknowledgement alone. The plugin re-reads playback state and returns `verified` only when the requested playing/streaming or cancelled/stopped state is observed. An unconfigured installation reports `voice-backend-not-configured` rather than inventing audio output.

## Adapter contract

A runtime backend implements:

- `describe()` -> normalized capability/locality metadata;
- `profiles()` -> bounded profile records;
- `synthesize(request)` -> stable artifact id plus format/sample-rate/duration/backend/profile evidence;
- `play(artifact_id)` -> provider acknowledgement with stable playback id;
- `playback_state(playback_id)` -> observed playback state;
- `cancel(playback_id)` -> provider cancellation acknowledgement.

Backend implementations may cache audio internally, but they must respect the configured output-duration and text limits and keep mutable cache/state outside the Nix store. Model weights and generated audio are not committed to this repository.

## Configuration

The service understands these optional values under `[plugins.zara-voice]`:

- `allow_remote` (default `false`)
- `max_text_bytes` (default `8192`)
- `max_duration_ms` (default `300000`)

Concrete provider adapters are injected/configured separately. The base plugin intentionally starts in an unavailable state when none is configured.

## Verification

Tests use fake backends only. They require no network, credentials, audio hardware, GUI, microphone, model weights, or live TTS service. They cover locality gating, profile validation, capability gating, input/output bounds, secret-free metadata, and verified playback/cancellation.
