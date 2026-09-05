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

## Configuration

`default_ttl_seconds` defaults to 30 seconds and is bounded to one hour.

## Verification

Tests use a fake clock and require no GUI, network, credentials, filesystem state, or sleeps. Repository compatibility/Nix gates cover runtime loading and metadata agreement.
