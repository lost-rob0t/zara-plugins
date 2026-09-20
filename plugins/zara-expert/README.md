# zara-expert

`zara-expert` is the reusable bounded Prolog expert-system host for Zara plugins.

It keeps knowledge bases and mutable facts isolated by plugin namespace, separates session facts from persistent facts, rejects unsafe executable Prolog terms before backend execution, forwards hard query/result/output limits, and returns structured query/explanation evidence.

## Runtime model

The plugin is a Zara API v1 service plugin. Mutable state lives under `$XDG_DATA_HOME/zarathushtra/zara-expert` by default, never in the immutable Nix package. A backend can be injected by a host integration; when no SWI-Prolog backend is configured the service reports `unavailable` and query/explain operations fail explicitly instead of pretending reasoning succeeded.

Other plugins register their own namespace and KB paths through `ExpertHost.register()`. Cross-plugin state mutation is not implicit.

## Language expert adapters

`zara_expert.language_adapters` provides Zara-side adapters for **PrologExpert**, **PythonExpert**, and **NimExpert**. The adapters deliberately do not embed those expert brains. Canonical expert definitions, builders, rules, style policy, and expert-specific tests live under the operator-owned `dotfiles/.zara/experts/` library; the adapters bind those installed artifacts to this existing host.

The adapter surface follows the draft `ZARA-EXPERT/1` descriptor contract from Zara #1233 and exposes a closed operation vocabulary: `applicable`, `inspect`, `diagnose`, `style`, and `explain`. Calls use fixed predicates and a validated symbolic `subject_id`; source text is never interpolated into a Prolog goal. Results preserve source/digest provenance, structured evidence, explanation trace, runtime generation, and `model_calls=0`.

Per-call timeout, result-count, and output-byte budgets can only narrow the host configuration. A symbolic language adapter rejects any invocation whose `max_model_calls` is nonzero. Repair/edit effects are intentionally not implemented here; they must cross Zara's canonical write/edit capability and approval boundary.

Project/per-language style integration is provided by loading the canonical style KB/overlay with the expert namespace and querying the fixed `expert_style_rule/2` predicate. This repository does not define a second style manifest or loader.

## Safe operations

- bounded `query` and `explain` calls;
- ground-fact `assert_fact` and idempotent `retract_fact`;
- separate session and persistent state files;
- namespace validation and atomic state writes;
- explicit backend failure propagation;
- bounded Prolog/Python/Nim expert adapter operations with zero model calls.

Arbitrary directives, shell/process predicates, consult/module loading from untrusted terms, assertion/retraction predicates inside query text, and compound control syntax are rejected before the backend sees them.

## Verification predicates

Domain plugins can define predicates such as `can_handle/1`, `required_tools/2`, `plan/2`, and `verify/2` inside their own KB. Language expert packages consumed by the adapters expose `expert_applicable/2`, `expert_evidence/2`, `expert_diagnostic/2`, `expert_style_rule/2`, and `expert_explanation/2`. The host returns backend evidence; a model claim is never treated as proof.

## Tests

```sh
python3 -m unittest discover -s plugins/zara-expert/test -t plugins/zara-expert/test
python3 scripts/validate-registry.py
nix flake check
```
