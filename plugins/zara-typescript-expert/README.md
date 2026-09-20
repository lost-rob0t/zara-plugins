# zara-typescript-expert

`zara-typescript-expert` is the Zara product adapter for **TypeScriptExpert** in the pure-symbolic expert factory.

## Ownership

Reusable language semantics are not duplicated here. `lost-rob0t/prolog-rlm#500` defines the upstream contract and now hands canonical expert source ownership to `lost-rob0t/dotfiles#292`, under `.zara/experts/typescript`. This package owns only Zara lifecycle/discovery/capability adaptation.

## ZARA-EXPERT/1 contract

Discovery is passive. The descriptor is pure symbolic, `fallback_policy=none`, `max_model_calls=0`, and declares only zero-effect operations. Invocation crosses the canonical `expert.invoke` capability using the closed ZARA-EXPERT/1 request, including request ID plus expected registry/runtime generations. The adapter rejects unknown/effectful operations, malformed input, nonzero model usage, stale/unbound results, missing evidence/explanation, and any side-effect receipt. There is no provider, credential, network, raw-Prolog-goal, subprocess, or model fallback.

TypeScript remains distinct from JavaScript; requested type semantics require the TypeScript expert.

Repair support in this package is verification-only (`repair_verify`). Applying an edit remains owned by Zara's canonical capability/approval/tool boundary and must provide fresh postcondition evidence.

## Tests

Top-level expert-factory contract tests cover passive discovery, exact zero-model invocation, stale-generation rejection, effect fencing, malformed input, and fail-closed provider-free behavior.
