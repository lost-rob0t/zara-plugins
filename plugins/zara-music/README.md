# zara-music

Prolog-first Zara Music commands over the canonical Zara Music service/runtime boundary.

This plugin is the semantic music surface. It does not scan the music filesystem, tunnel audio through ZARA/1, import `zara-media` internals, or own SSH credentials. Playback/media transport remains behind the configured Zara Music backend. Remote file retrieval belongs to the separate `zara-ssh` capability tracked by zara-plugins #851. The portable Prolog catalog maps `remote_ssh` retrieval to `ssh.file.fetch`, so symbolic planning can select that transport without importing SSH implementation code.

## Runtime / Prolog surface

The plugin registers canonical programmable command symbols and matching portable Prolog facts:

- `music:search` -> `music.search`
- `music:recommend` -> `music.recommend`
- `music:play` -> `music.play`
- `music:pause` -> `music.pause`
- `music:volume` -> `music.volume`
- `music:favorite-current` -> `music.favorite.current`
- `music:playlist-add-current` -> `music.playlist.add_current`

The Prolog contract is in `prolog/zara_music_tools.pl`. It classifies read/write effects and the supported recommendation strategies so Zara's symbolic layer can reason over the same names the runtime exposes. The runtime remains the effect authority; Prolog facts do not bypass capability checks or approvals.

## Tool surface

- `music.status`
- `music.current`
- `music.search`
- `music.recommend`
- `music.play`
- `music.pause`
- `music.volume`
- `music.favorite.current`
- `music.playlist.add_current`

Recommendations support `familiar`, `discovery`, `rediscovery`, `similar`, `era`, `mood`, `deep-cut`, `album-flow`, and `sonic-path`, matching Zara Music issue #1140.

Current-track mutations fail closed when nothing is playing. Volume is bounded to `0.0..1.0`. Search/recommendation counts and text inputs are bounded. Mutation results require explicit boolean `accepted` and `verified` evidence; truthy strings or provider acknowledgements do not count as success.

## Composition

The plugin calls only its configured Zara Music backend. Cross-plugin remote retrieval must use Core-owned capability composition with the future `ssh.file.fetch` capability from #851; do not import another plugin's private Python modules.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-music/test -t plugins/zara-music/test
python3 scripts/validate-registry.py
nix flake check
```
