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
View Channels, Send Messages, and Read Message History. The plugin does not
request Discord's privileged Message Content intent. Mentioned messages are
available normally; random-mode replies can still target an ordinary message,
but they are intentionally content-independent when Discord withholds its
message body. The `/zara ask` command is available in both servers and DMs.

Restart Zara after installing so its service-plugin host discovers the entry.
Slash commands are synchronized when the bot connects.

## Discord setup commands

The default policy is intentionally permissive for an installed bot: Discord
use is enabled, every user can talk to Zara in every channel, and tool approval
requests raised by accepted Discord turns are automatically approved. The
controller only auto-approves events whose conversation id is in Zara's
`discord:` namespace; desktop or other runtime turns are not approved by the
Discord plugin.

Setup commands require Manage Server (Discord's `manage_guild`) and server
owners/administrators are accepted by the runtime guard as well:

```text
/zara ask message:<text>
/zara status
/zara discord enabled:<true|false>
/zara restrict user:<member>
/zara access set mode:<open|restricted>
/zara users add user:<member>
/zara users remove user:<member>
/zara users clear
/zara channels add channel:<text-channel>
/zara channels remove channel:<text-channel>
/zara channels clear
/random on
/random off
/random chance percent:<0..100>
```

`/zara discord enabled:false` makes Zara ignore server messages and rejects
`/zara ask` until a manager enables it again. `/zara restrict user:<member>` is
the fast path for switching to restricted mode and authorizing the first user;
run it again or use `/zara users add` for additional users. `/zara access set
mode:open` returns to open access.

In `restricted` mode, only users added with `/zara users add` may talk. If one
or more channels are configured, Zara accepts messages in those channels and
their threads; `/zara channels clear` returns to all channels. These settings
are stored atomically in `settings.json` with mode `0600`.

Random mode is disabled by default. `/random on` enables spontaneous replies
for the current server with a default 5% chance per eligible non-bot message.
`/random chance` changes that probability. Access-mode and channel rules still
apply, so random mode never bypasses the configured policy. Random responses
use Discord replies and do not mention the author.

Direct messages are open while every server is in open mode. Once any server
uses restricted mode, a direct-message sender must be authorized in at least
one restricted server, so the server restriction cannot be bypassed through a
DM.

In a server, mentioning Zara with text sends that text to Zara. A bare `@Zara`
mention is also valid and asks Zara for a brief in-character response. Direct
messages are answered without a mention. All paths apply the same user and
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
