# zara-policy

A ServicePlugin that advises the model when **final answer text** matches executable Prolog rules. Version 0.1.0, Zara plugin API 1, GPL-3.0-or-later. Requires Zara's `zara.agent.output_policy` and `modules/output_policy.pl` core additions. It does not require Prolog-RLM or a second Prolog engine.

## Install and configure

Copy `zara-plugin/zara_policy.py` into a configured Zara module search directory (default `~/.zarathushtra/plugins/`). Create the private directory and explicitly install a reviewed rules file:

```sh
install -d -m 700 "${XDG_CONFIG_HOME:-$HOME/.config}/zarathushtra/plugins/zara-policy"
install -m 600 policy.example.pl "${XDG_CONFIG_HOME:-$HOME/.config}/zarathushtra/plugins/zara-policy/policy.pl"
```

Enable service-plugin discovery through Zara's existing plugin configuration, and enable around-advice in Zara's main `config.toml`:

```toml
[hooks]
enabled = true
allow_override = true
```

The private `plugins/zara-policy/config.toml` optionally contains `max_revisions = 2`. Valid values are 0–3. Zero checks once and withholds a matching draft without retrying. Missing/empty rules and invalid settings prevent startup. Unsupported hosts fail explicitly on use, not silently.

Rules are loaded through the **canonical PrologEngine** on the first LLM turn and reused. Edit and review `policy.pl`, then restart the plugin to reload. Rules are executable trusted code: use full Prolog bodies, helper predicates and permitted libraries, not just static facts. Do not install unreviewed rules from model output. Rule loading is not an untrusted-code sandbox.

## Rule API

```prolog
:- multifile output_policy:advice/5.

output_policy:advice(no_preamble, 100, Context, Text,
    "Remove the preamble and answer directly.") :-
    Context.principal_id == "local",
    output_policy:text_matches(icontains("as an ai language model"), Text).
```

`advice(IdAtom, PriorityInteger, HostContextDict, TextString, AdviceString)` is a normal executable multifile predicate. Context contains `principal_id`, `turn_id`, and `conversation_id`, supplied by the host rather than extracted from model text. Built-in matchers are `exact`, `contains`, `icontains`, `all`, `any`, and `not`. Additional matching logic can live in your Prolog rules. There is no built-in regex matcher in this version.

Rules can express tone, formatting, evidence wording and other application conventions. The example about tests is a wording demonstration, **not proof that tests really ran**. A matching draft produces advice; no matches allow it. Advice is ordered by priority then ID, with duplicate IDs treated as errors. Evaluation uses bounded core text/advice sizes and cooperative execution limits.

## Execution guarantees and limits

The existing agent loop executes once. Only model generation is retried. Original messages are not edited, advice is ephemeral, and accepted responses retain their provider metadata. Revisions cannot execute or introduce tools. Cancellation propagates. Invalid policy decisions and exhausted revision budgets fail closed for the final draft.

When enabled, final-answer generation is buffered: rejected drafts do not enter the graph's normal completion/chat/TTS publishing path. This trades token streaming for pre-publication checking. Initial tool-call messages, including any attached narration, pass through unchanged and retain normal approval requirements. This is **not** a tool-narration filter, tool authorization system, factual verifier, or universal security boundary. Hidden reasoning is not inspected. Native Prolog mode bypasses the model wrapper.

RuntimeHost owns plugin lifecycle and removes this plugin's advice registrations during shutdown. No network service, additional actor system, background polling or worker pool is created by the plugin. The canonical engine already serializes Prolog access. Trusted Prolog rules remain loaded in that engine after plugin stop, but no policy wrapper remains active once the owned hook is removed.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-policy/test -t plugins/zara-policy/test
python3 scripts/validate-registry.py
nix flake check
```

The plugin tests use API doubles to exercise lifecycle, settings, rule loading, exact-once continuation and host-context forwarding without installed Zara. The companion core tests cover actual adapter behavior; SWI-Prolog and real-manager tests must also pass in Zara's full environment before release.
