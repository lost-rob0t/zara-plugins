# zara-voice-lab

`zara-voice-lab` is the voice creation/cloning workbench. Routine runtime synthesis and playback belong in `zara-voice`.

## Data and locality boundaries

Backends declare `local` or `remote` locality and explicit capabilities such as `clone`, `create`, `preview`, and `style`. Remote processing is refused unless host policy explicitly enables it, so source voice samples are never silently uploaded.

Source audio is validated before backend execution. Per-sample, total-dataset, and preview-output byte limits are enforced. Samples are staged under the configured mutable workspace (default `$XDG_DATA_HOME/zarathushtra/zara-voice-lab`) and temporary source material is removed after each create operation.

## Provenance and export

Every created profile retains backend identity, backend runtime-profile ID, model identifier, backend configuration, creation mode, locality, and caller-supplied source provenance. Export uses `zara-voice-profile-v1` metadata so the runtime plugin can consume a stable profile description without embedding source samples, generated artifacts, or model weights.

Preview results expose bounded format/duration/size metadata but not raw audio through the Zara tool surface. The default registry service has no configured backend and reports `voice-lab-backend-not-configured` honestly.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-voice-lab/test -t plugins/zara-voice-lab/test
python3 scripts/validate-registry.py
nix flake check
```

Tests use fake backends only and require no real training, network access, or audio hardware.
