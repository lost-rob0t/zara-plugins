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
View Channels, Send Messages, and Read Message History. Message Content remains
off by default. Mentioned messages and `/zara ask` work without the privileged
intent.

Random/inspection mode is the explicit opt-in boundary for ordinary message
bodies. `/random on` persists that opt-in for the guild. To inspect message
bodies, enable **Message Content Intent** for the bot in the Discord Developer
Portal and restart Zara. On startup, the plugin requests Message Content only
when at least one persisted guild or channel has inspection enabled. If no
policy opts in, the privileged intent is not requested.

Until restart, or whenever Discord does not provide the privileged intent,
inspection turns explicitly include `content_available=false` and instruct Zara
that only metadata-level reasoning is valid. The plugin must not claim it read
the message body. When the intent is active, inspection context marks
`content_available=true` and includes the available body. If Discord rejects a
requested privileged intent, the gateway fails clearly with Developer Portal
recovery instructions instead of pretending inspection succeeded.

Disabling guild random mode removes that guild default. Channel overrides can
still independently enable inspection; when every guild default and channel
override is disabled, the next Zara restart returns to the non-privileged
gateway configuration.

Restart Zara after installing so its service-plugin host discovers the entry.
Slash commands are synchronized when the bot connects.

## Conversation context

Each Discord user gets a distinct Zara conversation id inside each channel or
DM. Conversation ids contain numeric Discord guild/channel/user ids only; they
do not embed usernames or display names. Two people speaking in the same shared
channel therefore cannot inherit one another's bounded transcript history.

The plugin keeps the most recent routed user turns plus Zara responses and
failures in an in-memory history and prepends that history to the next turn.
This makes short follow-ups such as `retry`, `do that again`, or `use the
previous file` retain the immediately preceding conversation for that same
Discord user and channel even when the underlying model starts a fresh session
for the new turn.

History is bounded to 12,000 characters per conversation and at most 256 active
conversations. Oldest entries are evicted first, oversized entries are clipped,
and separate users/channels never share history. The current message is outside
the history budget, so a long new request cannot evict itself before
submission. The history is deliberately process-local and resets when the Zara
service restarts; it does not scrape arbitrary channel backlog.

## Discord setup commands

The default policy is intentionally open: every user can talk to Zara in every
channel. Setup commands require Manage Server (Discord's `manage_guild`) and
server owners/administrators are accepted by the runtime guard as well:

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
/random on
/random off
/random chance percent:<0..100>
/random channel set enabled:<bool> percent:<0..100> trigger_prompt:<text> response_style_prompt:<text> moderation_enabled:<bool> [channel:<text-channel>]
```

In `restricted` mode, only users added with `/zara users add` may talk. If one
or more channels are configured, Zara accepts messages in those channels and
their threads; `/zara channels clear` returns to all channels. These settings
are stored atomically in `settings.json` with mode `0600`.

Random mode is disabled by default. `/random on` enables spontaneous replies
for the current server with a default 5% chance per eligible non-bot message
and records the guild-level Message Content opt-in described above. When the
current process did not start with that intent, the command explicitly tells
the operator to enable the Developer Portal toggle and restart Zara; until
then, inspection remains metadata-only. `/random chance` changes the guild
default probability. Access-mode and channel rules still apply, so inspection
never bypasses the configured access policy.

`/random channel set` creates a complete per-channel override. With no `channel`
argument it targets the current channel; with a selected text channel it targets
that channel instead. The override carries enabled state, probability, trigger
instructions, response-style instructions, and the moderation flag. A channel
override wins over guild inspection defaults. If a configured trigger does not
match, Zara is instructed to return a reserved no-reply sentinel; the plugin
suppresses that sentinel before Discord output and before conversation history.

### CI/update-channel preset

For a noisy build/update channel, this opt-in preset inspects every available
message but only speaks when the body clearly reports a failed/red build. It
explicitly excludes warnings, successful/green builds, and ordinary status
updates:

```text
/random channel set \
  enabled:true \
  percent:100 \
  trigger_prompt:"Reply only when this message clearly reports a failed, failing, broken, or red build/test/deploy. Do not reply to warnings, success messages, green/passing builds, queued/running updates, or neutral status messages." \
  response_style_prompt:"Keep it very short and funny; something in the vibe of: ooops i fucked up again" \
  moderation_enabled:false
```

That preset is deliberately not global. Apply it only to channels where you
want Zara inspecting CI/update traffic, then enable Message Content Intent in
the Discord Developer Portal and restart Zara if body inspection is required.
Without the privileged intent, Zara receives metadata-only inspection context
and cannot honestly decide whether a body reports a failed build.

## Scoped moderation

Moderation is off unless the channel inspection override sets
`moderation_enabled:true`. When enabled, an eligible Discord turn receives a
short-lived in-memory capability token bound to exactly that guild, channel,
message, and current message author. The model never supplies arbitrary Discord
IDs to moderation operations.

Zara registers six ordinary service-plugin tools through the canonical
`ServicePlugin.tools()` API:

```text
discord_moderation_inspect
discord_moderation_delete
discord_moderation_warn
discord_moderation_timeout
discord_moderation_kick
discord_moderation_ban
```

Inspection may resolve the token more than once while it remains live. Every
mutating operation consumes the token before execution, so it cannot be replayed
for a second mutation. Tokens expire after two minutes, are bounded in memory,
and are never written to plugin settings or the moderation audit file.

Immediately before an operation, the gateway re-resolves the current Discord
guild, channel, message, author, and member and verifies they still match the
capability. Cross-message or cross-guild mismatches fail closed. The guild owner,
Zara itself, other bots, administrators, and members with manage-guild or
moderation permissions are protected targets. Discord's own permission and role
hierarchy remains a second enforcement gate.

Reasons are plain bounded text and timeouts are capped at 28 days. A mutation is
reported as successful only after the Discord API call returns successfully;
timeouts and API errors are explicit failures. Successful warn/timeout/kick/ban
actions may emit a configured mention-safe public acknowledgement. Delete does
not invent one.

Moderation decisions use the bounded local audit trail under Zara's XDG state
directory. It records numeric scope IDs, action, outcome, actor, and a sanitized
reason only. It never records raw message bodies, usernames/display names,
attachments, capability tokens, bot secrets, or model transcripts.

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
