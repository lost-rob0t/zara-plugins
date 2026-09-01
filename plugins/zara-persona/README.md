# zara-persona

`zara-persona` exposes operator-owned persona/style context to Zara without storing that context in the plugin repository.

The plugin has empty public defaults. Your prompt text and Prolog program can live in private local files and are read only at runtime. When Zara calls the `persona_context` tool, the resulting context is sent to the currently configured model as tool output, so keep model/provider privacy in mind.

## Nix install

```sh
nix build github:lost-rob0t/zara-plugins#zara-persona
```

With the declarative Home Manager integration, select `zara-persona` from the pinned registry and keep private files outside the Nix store.

## Configuration

Zara plugin configuration uses `[plugins.zara-persona]`:

```toml
[plugins.zara-persona]
enabled = true
prompt_file = "/home/me/.config/zarathushtra/private/persona.txt"
prolog_enabled = true
prolog_file = "/home/me/.config/zarathushtra/private/persona.pl"
prolog_timeout_seconds = 2.0
prolog_output_limit = 16384
max_chars = 4000
```

The file paths may also be supplied through the Zara service environment:

```text
ZARA_PERSONA_PROMPT_FILE=/home/me/.config/zarathushtra/private/persona.txt
ZARA_PERSONA_PROLOG_ENABLED=true
ZARA_PERSONA_PROLOG_FILE=/home/me/.config/zarathushtra/private/persona.pl
ZARA_PERSONA_SWIPL=swipl
```

Explicit plugin configuration takes precedence over environment fallbacks.

## Prolog contract

The plugin executes only the fixed predicate `zara_persona:context/1`. The predicate must return a Prolog string.

```prolog
:- module(zara_persona, [context/1]).

context("Be concise, direct, and technically precise.").
```

The subprocess is non-interactive, has a configurable timeout, and rejects output beyond the configured size limit.

## Prompt file

A prompt file is plain UTF-8 text. It can contain any local persona/style policy you want. The repository does not need to know or package its contents.

## Tool behavior

The plugin registers one tool:

- `persona_context` — returns the configured inline prompt, prompt-file text, and optional Prolog-produced context joined together.

If you want the model to consult it consistently, add a short instruction to your own Zara agent system prompt telling the model when to call `persona_context`.
