# zara-policy 0.1.0

A Plugin API v1 service that reviews model text using an operator-extensible
Prolog knowledge base. It provides `policy.inspect` and `policy.status`, and
can advise the model through Zara's existing agent-loop advice API. It does
not depend on Prolog-RLM or add a second conversation/tool execution loop.

## Defaults and activation

The bundled `lib/zara_policy/config.pl` is copied, only when absent, to
`$XDG_CONFIG_HOME/zarathushtra/plugins/zara-policy/config.pl` (default
`~/.config/zarathushtra/plugins/zara-policy/config.pl`). The shipped KB is
loaded automatically before that file. Existing user files are not overwritten.

Defaults: `advise`, one repair attempt, 20-second repair deadline, 65,536
input characters, `balanced` profile. The catalogue contains **40 rules and
250 original phrase patterns**. Broad-refusal review is disabled; stylistic
rules require the `direct` profile. Honest uncertainty is not a failure rule.

Install/discover the entrypoint using the registry's existing installation
mechanism. The ready startup profile at `profiles/prolog-policy/config.toml`
autoloads both services and enables the existing advice gates. Merge its
settings rather than replacing an existing configuration or losing other
plugins. `hooks.enabled` and `hooks.allow_override` must both be true for
automatic advice. This plugin does not secretly enable either gate. Without
them, inspection remains available and `policy.status` reports `hooks-disabled`.
Other installed around/override hooks also become eligible under these gates;
review the installed hook set before enabling them.

```prolog
zara_policy:setting(mode, advise).       % off | observe | advise
zara_policy:setting(max_repairs, 1).     % 0 | 1
zara_policy:setting(timeout_seconds, 20).
zara_policy:setting(max_text_chars, 65536).
zara_policy:setting(profile, balanced). % balanced | direct
zara_policy:setting(review_refusals, false).
```

Keep exactly one setting fact per key. To change a setting, edit its existing
fact rather than adding a duplicate. Restart the service to reload policy
code. Automatic live reload is intentionally not implemented in this version.

## Extend the knowledge base

Add these clauses to the user config or load a trusted `.pl` extension from it:

```prolog
:- multifile zara_policy:rule/6, zara_policy:pattern/2,
             zara_policy:disabled/1, zara_policy:override/3.

zara_policy:rule(local_hype, style, info, always,
    "Replace hype with a concrete description.", local).
zara_policy:pattern(local_hype, "magic pixie dust").
zara_policy:disabled(flattery).
zara_policy:override(test_claim, severity, info).
zara_policy:override(test_claim, advice,
    "Keep the claim only with the exact command, result and tested revision.").
```

The schema is `rule(Id, Category, Severity, Gate, Advice, Source)` with one or
more `pattern(Id, Phrase)` clauses. IDs are stable lowercase identifiers.
Severities are `info`, `warning`, `error`. Gates are `always`, `assertion`,
`direct`, `refusal_review`. `assertion` suppresses matches preceded by common
negation/conditional markers in the same sentence. Configuration, duplicate
IDs, unknown overrides and size bounds are validated before startup.

Patterns match contiguous whole tokens, case-insensitively. Python only
normalizes presentation and masks fenced/indented code, Markdown blockquotes,
inline code and double-quoted examples; Prolog owns classification and advice.
This is not a complete Markdown parser or semantic negation detector.

`policy.inspect` reports IDs, categories, severities, advice and provenance
labels. It never evaluates input text as Prolog or as a prompt. The API does
not accept model-supplied claims that a tool action was verified.

## Model advice and streaming

The around hook wraps the existing model client, not the tool loop. The first
answer is scanned; matching rules produce trusted feedback, and at most one
additional call is made to the original unbound model. The replacement is
accepted only when it remains text-only, fits the size limit and reduces the
heuristic severity score. Otherwise the original answer is returned.

Tool calls, invalid tool calls, raw function calls and non-text content blocks
bypass repair. Repair-generated tool calls are rejected and never executed.
Cancellation propagates. Scan/repair errors preserve the original response and
emit a sanitized warning. This is advisory fail-open behavior, not enforcement.

Reviewed streaming is **buffered**: only the selected final response is emitted
as a chunk, so an unreviewed draft is not spoken or displayed first. This
increases time to first token and loses fine-grained provider streaming.
Repairs can increase token use and cost. Fewer matches do not prove factual
correctness or better quality; compare reviewed responses in your own evals.

## Trust boundary and limits

This is an **operator-scoped desktop/server plugin**, not a per-tenant sandbox
or an Android engine implementation. It uses Zara's canonical process-wide
`PrologEngine` serialization. User config is executable, trusted Prolog; it
can load libraries and run code. Do not load untrusted downloaded rule files.

No transcript text is retained in plugin diagnostics. The canonical engine
may still log consulted-file load errors; do not put secrets in source.
Matching uses bounded input, rule/pattern counts, findings, inference work and
one asynchronous scan admission slot. SWI time/inference limits are cooperative,
not protection against arbitrary native code, `halt/0` or hostile directives.

The phrase list cannot establish whether a claim is true, whether a refusal
is justified, or whether content is AI-generated. Sources in `RESEARCH.md`
inform categories; the exact phrases are locally authored heuristics.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-policy/test -t plugins/zara-policy/test
ZARA_REQUIRE_SWIPL=1 python3 -m unittest discover -s plugins/zara-policy/test -t plugins/zara-policy/test
```

The first command explicitly skips native semantics when SWI is absent; the
second must fail in that case. Repository CI runs the required native gate.
License: GPL-3.0-or-later.
