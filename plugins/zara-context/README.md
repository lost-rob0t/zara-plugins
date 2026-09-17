# zara-context

A short-lived structured context service for resolving references such as “this repo”, “that file”, and “the current workspace” without persisting desktop state as memory.

## Model

Context items carry a category, JSON value, source/provenance, observation time, expiry time, and confidence. Supported initial categories include application/window/workspace, project/repository/file, selection/clipboard, recent command, media, and call state.

Expired items are returned separately as `stale`; they are never silently presented as current context. Adapters can remove expired values after consumers have had a chance to observe the stale state.

## Privacy

- context is process-local and never automatically persisted;
- values are byte-bounded;
- consumers can request only known categories;
- selected text and clipboard data are not logged by this plugin;
- persistent memory remains the responsibility of an explicit memory plugin/policy.

## Adapter boundary

Desktop/editor/browser/file plugins may publish context through the service's structured `publish_context()` boundary. This is intentionally not a model tool: the model can query context but cannot forge trusted desktop observations through the public tool surface.

The initial query tool is `context.current(categories="")`. Backend event integrations should push updates from their native event streams; polling is a fallback adapter concern rather than the context model.

## Android: Zara Activity

`activity-android/` is a separately permissioned Android companion APK (`ai.zara.activity`) for bounded ActivityWatch-style app-time summaries. It reads Android's existing `UsageStatsManager` history only after explicit Usage Access, has no Internet/Accessibility/screen-capture permission, and does not change the process-local persistence semantics of the core context service.

Until Zara's canonical `ZARA-ANDROID-PLUGIN/1` host boundary is available, Zara Activity remains a standalone local dashboard rather than inventing a second plugin authority path. See `activity-android/README.md` and zara-plugins#826.

## Configuration

`default_ttl_seconds` defaults to 30 seconds and is bounded to one hour.

## Verification

Tests use a fake clock and require no GUI, network, credentials, filesystem state, or sleeps. Repository compatibility/Nix gates cover runtime loading and metadata agreement. The Android companion has an additional standalone APK/emulator gate.
