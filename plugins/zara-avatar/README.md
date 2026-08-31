# zara-avatar

Zara-owned 3D avatar presentation plugin for [Zara](https://github.com/lost-rob0t/zara)'s
service-plugin API. Zara's brain, memory, and relationship state live elsewhere;
this plugin owns only presentation: the selected avatar, its visible state,
expression, animation, gaze, speech visuals, and the renderer child process.

- loopback-only HTTP/SSE control surface with bounded resources
- VRM (0.x and 1.0) avatars rendered by a replaceable Electron + Three.js child
- procedural presence (idle / listening / thinking / speaking), expressions,
  gestures, gaze, audio-driven visemes, VRMA animation playback
- authoritative avatar state owned by a single serialized actor; HTTP handlers
  and event subscriptions send commands, they never mutate state directly

## Requirements

- Zara with the public service-plugin API (`zara.plugins`, plugin API version `1`)
- Python 3.13+ (stdlib only — no extra Python dependencies)
- For rendering: Electron + Three.js via the bundled renderer (`npm install`
  once; the only network-required step)

## Install

From a checkout of this repository:

```sh
python3 plugins/zara-avatar/tools/zara-avatar install
```

That copies `zara-plugin/zara_avatar.py` into Zara's plugin directory
(`~/.zarathushtra/plugins` by default) and the renderer into
`~/.local/share/zara/renderer`, then runs `npm install` for the renderer.

With Nix:

```sh
nix run github:lost-rob0t/zara-plugins#zara-avatar -- install
```

The plugin resolves its renderer command in this order:

1. `renderer_command` in Zara's `[plugins.zara-avatar]` configuration
2. `ZARA_AVATAR_RENDERER` environment variable
3. `renderer/node_modules/.bin/electron main.mjs` next to the checkout
4. `~/.local/share/zara/renderer/node_modules/.bin/electron main.mjs`

## Configuration

All settings are optional and live in Zara's `config.toml`:

```toml
[plugins.zara-avatar]
enabled = true
port = 7321                      # loopback HTTP/SSE control port (0 = ephemeral)
avatar_directory = "~/.local/share/zara/avatars"
# renderer_command = ["/path/to/electron", "/path/to/main.mjs"]
```

## Control surface

The plugin serves `http://127.0.0.1:7321` only. Use the bundled CLI or plain
HTTP/SSE:

```sh
zara-avatar status                                   # avatar status document
zara-avatar import ada Ada.vrm                       # import a VRM avatar
zara-avatar select ada                               # select and load
zara-avatar show | hide | unload
zara-avatar emotion happy | gesture wave | expression surprised
zara-avatar animation play wave --loop --speed 1.5
zara-avatar gaze user | --point X Y Z
zara-avatar speech-begin | speech-audio FILE | speech-end | speech-cancel
```

Endpoints: `GET /v1/avatar/status`, `GET /v1/avatar/events` (SSE), and
`POST /v1/avatar/*` command routes (`import`, `select`, `show`, `hide`,
`emotion`, `gesture`, `gaze`, `animation`, `speech/*`, ...). Requests from
non-loopback clients are rejected; bodies, queues, connections, and workers
are all bounded.

## Tests

```sh
python3 -m unittest discover -s plugins/zara-avatar/test -t plugins/zara-avatar/test
```

225 tests cover the actor, protocol, library, lip sync, renderer process,
CLI, and plugin lifecycle. Tests that need a real Zara source tree are
skipped when Zara is not available locally.

## License

GPL-3.0-or-later, matching the registry and Zara.
