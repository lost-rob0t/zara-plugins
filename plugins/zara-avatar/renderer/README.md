# Zara avatar renderer

Zara's local real-time 3D renderer. Electron + Three.js + @pixiv/three-vrm.
It renders Zara's VRM avatars (0.x and 1.0) with MToon materials, spring
bones, expressions, procedural presence, VRMA animation playback, and
audio-driven visemes.

The renderer is replaceable: it speaks one newline-delimited JSON protocol on
stdio (see `zara-plugin/zara_avatar.py`, `RENDERER_COMMANDS`) and never
exposes Three.js objects across that boundary.

## Install (once)

Either let the installer do it (no Emacs needed):

```sh
tools/zara-avatar install            # copies renderer to ~/.local/share/zara
                                     # and runs npm install there
```

Or manually:

```sh
cd renderer
npm install
```

This is the only step that needs network access. After it, the renderer works
fully offline.

## Run

The plugin launches the renderer automatically. It resolves the command in
this order:

1. `renderer_command` in Zara's `[plugins.zara-avatar]` configuration
2. `ZARA_AVATAR_RENDERER` environment variable
3. `renderer/node_modules/.bin/electron main.mjs` (this repository)
4. `~/.local/share/zara/renderer/node_modules/.bin/electron main.mjs`

Manual run for development:

```sh
cd renderer
npx electron main.mjs
```

## Protocol summary

Requests in (one JSON object per line on stdin):

```json
{"id": 1, "command": "LoadAvatar", "params": {"avatarId": "a", "path": "/abs/path.vrm", "seed": 7}}
```

Responses and events out on stdout:

```json
{"id": 1, "ok": true, "result": {"expressions": ["neutral", "happy"]}}
{"event": "ready", "params": {"renderer": "electron"}}
```

Commands: `LoadAvatar`, `UnloadAvatar`, `SetExpression`, `SetTransform`,
`SetCamera`, `SetGaze`, `SetVisemes`, `SetLighting`, `PlayAnimation`,
`StopAnimation`, `ShowWindow`, `HideWindow`, `Shutdown`.

## Animations

Semantic animation names map to files through `animations/manifest.json`:

```json
{"wave": "wave.vrma", "nod": "nod.vrma"}
```

Only place redistributable animation files here. Bundled catalogs from other
projects must never be copied into this directory.

## Display modes

The first milestone is a normal desktop window. The window is created with
`ShowWindow` params `{transparent: true, alwaysOnTop: true}` supported for a
later overlay milestone; framing presets (`half`/`full`) are applied through
`SetCamera`.
