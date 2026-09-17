# zara-policy 0.1.0

Optional, native **SWI-Prolog output-policy plugin** for Zara. Matching, priorities,
exceptions, configuration and corrective advice live in Prolog. Python supplies
bounded JSON transport and the existing Zara service/LangChain interfaces. No
Prolog-RLM dependency, second agent loop or blanket word blacklist.

The default KB contains **75 rules, 291 phrase alternatives and 16 categories**:
completion, future work, task progress, certainty, evidence, capability,
sycophancy, completeness, verification, reasoning, freshness, scope, privacy,
authority, repair and style. Style is disabled by default. See [SOURCES.md](SOURCES.md)
for research, the distinction between evidence and heuristics, and limitations.

## Install and default configuration

Requires Python 3.11+, Linux and SWI-Prolog; the Zara service also uses Zara's
existing `langchain-core`. Nix packages include SWI in the policy runtime only.

```sh
nix run github:lost-rob0t/zara-plugins#zara-policy -- install
# From a checkout, with SWI and Zara already installed:
python3 plugins/zara-policy/tools/zara-policy install
```

The installer creates, but **never replaces an existing**, mode-0600 operator file:

```text
$XDG_CONFIG_HOME/zarathushtra/plugins/zara-policy/config.pl
# XDG_CONFIG_HOME defaults to ~/.config
```

Its shipped defaults are real executable Prolog:

```prolog
:- multifile zara_policy:option/2.
zara_policy:option(mode, advice).
zara_policy:option(max_findings, 8).
zara_policy:option(disabled_categories, [style]).
```

Enable the installed service in the existing root `config.toml`:

```toml
[plugins.zara-policy]
enabled = true
```

`examples/config.toml` also shows optional automatic advice using Zara's existing
`[hooks] enabled = true`, with `allow_override = false`. Hook enablement is a
broader trust decision: it enables other installed hooks too. Installation does
**not** silently enable it or overwrite the user's root config. Keep a Nix profile
or other GC root retaining the package when using its immutable discovery entry.

## Model-facing tools and advice timing

`policy_advice(text)` returns findings, priorities, rule IDs, configured matching
phrases, source IDs and actionable advice. `policy_rules(offset=0, limit=16)`
exposes the complete catalog and disabled-rule status. Both use standard
LangChain tools, not a parallel registry. No tools write policy files.

With ordinary loop hooks enabled, the plugin injects brief draft-review guidance
and advice matched against the **previous completed assistant answer in this
conversation**. It removes that temporary system message in the after-loop hook
before normal history persistence. No transcript text is stored in the plugin or
copied into trusted guidance; only operator-authored advice is injected.

**This is not a guaranteed same-turn pre-send gate.** The model can call the draft
review tool before answering. Automatic advice otherwise takes effect on the next
turn; existing streaming output is not intercepted or rewritten. The plugin does
not replay tools, bypass approvals or automatically invoke another LLM. Missing
hook support leaves tools available. Disabled hooks remain disabled.

A typical finding for `All tests pass.` requests the exact test command, candidate
revision and observed result. It does not infer whether tests really passed from
that sentence. `verdict` is always `not_assessed`; no match is not verification.

## First-class Prolog API and user extensions

```prolog
?- use_module('lib/zara_policy/prolog/policy.pl').
?- zara_policy:advise("All tests pass.", _{}, Report).
?- zara_policy:rules(Rules).
?- zara_policy:validate.
```

The module works directly without Python. Consult the operator config after it.
Defaults load first; later options win. New IDs extend the KB, matching IDs replace
the entire default rule, `disabled(Id)` disables a rule, and
`suppress(Id, Matcher)` supplies a local exception. See `examples/user-policy.pl`.

```prolog
:- multifile zara_policy:user_rule/6.
zara_policy:user_rule(completion_tests, verification, 98,
    any(["all tests pass", "ci is green"]),
    "Give the exact command, exit status and commit SHA.", [local]).
```

Matchers: `phrase(String)` or a string, `any(List)`, `all(List)`,
`unless(Matcher, Exception)`, `count(String, N)` and `flag(Key, Value)`.
`all`, `count` and exceptions apply within one prose segment. Native trusted
adapters can pass structured evidence to `advise/3`; the model-facing tool always
supplies an empty context and cannot assert trusted execution facts.

Operator configuration is **trusted executable code**, not a sandbox: directives
can use libraries and execute with the runtime user's permissions. Do not
consult generated text or downloaded KBs without explicit code review. Requests
are stateless fresh processes, so changing the config takes effect on the next
review; a broken config returns unavailable rather than silently reusing stale
rules. Author side-effect-free rules unless deliberate execution is needed.

## Bounds, failures and matching limitations

Unicode alphanumeric token matching avoids substring hits and ignores case and
punctuation. The matcher skips triple-backtick/tilde fences, four-space indented
code, blockquotes, inline backticks, straight double quotes and curly double quotes.
A conservative six-token negation window reduces common false positives. This
is **not** a full Markdown parser or semantic negation model. Single-quoted text,
line wrapping, unusual quoting, indirect attribution and paraphrases can produce
false positives or misses. Finding segment numbers refer to processed prose, not
original character offsets. Never use lexical matches alone to block output.

Limits: 32,768 input characters, 256 KiB request/response, 4 KiB stderr, 512 rules,
matcher depth 8, up to 32 matches (8 by default), two concurrent subprocesses,
2-second Prolog evaluation and 3-second transport timeout. Process errors,
missing SWI, invalid configuration, oversize data and busy capacity yield explicit
unavailability, not a clean verdict. Linux subprocess groups are terminated on
failure. These bounds are resource controls, not OS isolation for trusted config.
`ZARA_POLICY_SWIPL` and `ZARA_POLICY_CONFIG` are operator overrides.

```sh
printf '%s\n' 'All tests pass.' | python3 plugins/zara-policy/tools/zara-policy advise
python3 plugins/zara-policy/tools/zara-policy rules --limit 16
python3 -m unittest discover -s plugins/zara-policy/test -t plugins/zara-policy/test -v
ZARA_POLICY_REQUIRE_SWIPL=1 python3 -m unittest discover -s plugins/zara-policy/test -t plugins/zara-policy/test -v
```

Tests explicitly skip native SWI/real-Zara checks when dependencies are absent;
`ZARA_POLICY_REQUIRE_SWIPL=1` makes missing SWI a failing gate. The focused GitHub
workflow installs real SWI. The repository's normal Nix/compatibility gates still
apply before release. This change does not add an Android on-device Prolog runtime
or a Prolog editor UI.

License: GPL-3.0-or-later. Publication tracked by zara-plugins issue #811.
