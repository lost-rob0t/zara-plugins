# zara-media

Provider-neutral media playback, queue, player/device, and catalog tools for Zara.

A backend adapter owns the actual player/service integration. The public model stays normalized across local players, streaming services, video, podcasts, and future adapters. Without a backend the plugin reports `media-backend-not-configured`; it never fabricates playback success.

## Normalized model

Media items contain only bounded portable fields: `media_id`, `kind`, `title`, optional `artist`/`show`, `duration_ms`, and `provider`. Player state contains an opaque `player_id`, human-readable name/device, playback state, volume/mute, position, and the normalized active item. Provider tokens, cookies, device credentials, and adapter-specific response bodies are not part of the schema.

`media.context` exposes the same normalized active player/playback shape for consumers such as `zara-context`.

## Surface

- `media.status`
- `media.players`
- `media.playback.state`
- `media.context`
- `media.player.select`
- `media.playback.control`
- `media.queue`
- `media.queue.add`
- `media.queue.move`
- `media.search`
- `media.like_this`

Playback control is allowlisted to play/pause/stop/seek/skip-next/skip-previous/volume/mute and requires an explicit player ID. Volume, seek positions, queue sizes, search queries, results, and metadata are bounded.

## Verification semantics

State-changing operations preserve backend acceptance plus observed post-state. An accepted request is not automatically successful: player selection, play/pause/stop, seek, volume, mute, queue append, and queue reorder are verified against a fresh backend observation. When the backend refuses the operation or observation does not match, the result is `verification_failed`.

Skip verification requires an observed state change; adapters that cannot expose post-skip evidence should fail/degrade honestly rather than claiming success.

## Backends

Tests use an in-memory fake backend only and require no audio/video device, GUI, network, streaming account, or credentials. Production desktop/media-key or provider adapters remain behind the same interface. Zara Core remains responsible for normal tool authorization and approval policy.
