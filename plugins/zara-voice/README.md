# zara-voice

`zara-voice` owns Zara's normal runtime speech-synthesis surface without coupling Zara Core to a particular TTS engine. Voice cloning, dataset construction, and model training belong in `zara-voice-lab`.

## Runtime contract

Backends declare an explicit `locality` (`local` or `remote`) and a capability set. Profiles bind a Zara-visible name to one backend/profile pair. `voice.synthesize` validates text length and capability-gates optional language, style, and emotion controls before calling a backend. Remote backends are refused unless host policy explicitly enables them.

Synthesis returns normalized metadata (`backend`, Zara profile, backend profile, locality, format, sample rate, duration, request ID, artifact ID). Raw audio bytes remain internal to the runtime/player path and are not returned through the tool surface.

## Bounds and cancellation

The domain enforces configurable limits for input text, generated audio bytes, duration, and on-disk cache size. Cache data defaults under `$XDG_CACHE_HOME/zarathushtra/zara-voice`, outside the Nix store, and oldest artifacts are evicted to stay under policy. Backend over-limit output fails before being cached.

Playback and synthesis cancellation use explicit IDs. Synthesis cancellation is only reported successful when the selected backend reports cancellation; playback cancellation similarly preserves player evidence.

## Provider availability

The default registry plugin ships with no TTS backend or player configured and reports `tts-backend-not-configured` rather than pretending speech is available. Concrete local/remote adapters can be injected without changing the public tool schema. Secrets remain backend configuration and are never exposed by status output.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-voice/test -t plugins/zara-voice/test
python3 scripts/validate-registry.py
nix flake check
```

Tests use fake TTS/player adapters only and require no network or audio hardware.
