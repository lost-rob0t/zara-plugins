# Zara Discord

`zara-discord` is a Zarathushtra service plugin backed by `discord.py`. It
keeps Discord policy in the plugin's XDG configuration directory and sends
accepted messages through Zara's existing `PluginRuntime`.

## Install

From this repository checkout:

```sh
python3 plugins/zara-discord/tools/zara-discord install

# Or use the dependency-complete Nix app:
nix run .#zara-discord -- install
```

The installer places the Zara discovery entry at
`~/.zarathushtra/plugins/zara_discord.py` and the plugin code/configuration at
`$XDG_CONFIG_HOME/zarathushtra/plugins/zara-discord/` (or
`~/.config/zarathushtra/plugins/zara-discord/` when `XDG_CONFIG_HOME` is unset).
It preserves an existing `settings.json` and `token` file.

Before starting Zara, provide the Discord bot token in one of these ways:

```sh
export ZARA_DISCORD_TOKEN='paste-the-token-in-your-secret-manager-shell-only'
```

or write it to the installed config directory's `token` file and run
`chmod 600` on that file. The token is the one bootstrap value that cannot be
set through Discord: the bot must authenticate before Discord can deliver a
slash command. Do not commit or paste it into this repository.

Invite the bot with the `bot` and `applications.commands` scopes and grant it
View Channels, Send Messages, and Read Message History. The plugin uses
mention-only server messages and direct messages, so the privileged Message
Content intent is not required. The `/zara ask` command is available in both
servers and DMs.

Restart Zara after installing so its service-plugin host discovers the entry.
Slash commands are synchronized when the bot connects.

## Discord setup commands

The default policy is intentionally open: every user can talk to Zara in every
channel. Setup commands require Manage Server (Discord's `manage_guild`):

```text
/zara ask message:<text>
/zara status
/zara access set mode:<open|restricted>
/zara users add user:<member>
/zara users remove user:<member>
/zara users clear
/zara channels add channel:<text-channel>
/zara channels remove channel:<text-channel>
/zara channels clear
```

In `restricted` mode, only users added with `/zara users add` may talk. If one
or more channels are configured, Zara accepts messages in those channels and
their threads; `/zara channels clear` returns to all channels. These settings
are stored atomically in `settings.json` with mode `0600`.

Direct messages are open while every server is in open mode. Once any server
uses restricted mode, a direct-message sender must be authorized in at least
one restricted server, so the server restriction cannot be bypassed through a
DM.

In a server, ordinary messages are answered when the bot is mentioned. Direct
messages are answered without a mention. Both paths apply the same user and
channel policy as `/zara ask`.

## Development

```sh
python3 scripts/validate-registry.py
python3 -m unittest discover -s plugins/zara-discord/test -t plugins/zara-discord/test
nix flake check
```

The service plugin API and lifecycle remain owned by Zarathushtra; this
plugin supplies the Discord integration and its private configuration. The
publication request and acceptance criteria are tracked in issue #20.
