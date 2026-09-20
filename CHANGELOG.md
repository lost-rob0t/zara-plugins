# Changelog

## Unreleased

- Move project-owned symbolic expert source to `lost-rob0t/dotfiles/.zara/experts/`; zara-plugins retains runtime and adapter ownership rather than duplicate expert KBs.

### zara-expert
- Add provider-free PrologExpert, PythonExpert, and NimExpert adapters over canonical Dotfiles-owned expert sources.
- Route applicability, evidence, diagnostics, style rules, repair preview/verification, and explanation through host-issued registered-predicate authority with `max_model_calls=0`.
- Expose closed applicability/result schemas and canonical runtime symbols; `repair.apply` remains behind Zara's typed edit/effect authority with fresh postcondition verification.
- Preflight every configured language expert source before namespace registration so an invalid later source cannot leave a partially activated Prolog/Python/Nim family.
- Preflight both the Prolog/Python/Nim brain ABI and existing registered-predicate namespace authority before activating any Lisp or language family, preventing cross-family partial startup on source or authority conflicts.
- Preserve ZARA-EXPERT/1 verdict semantics for empty symbolic result sets: missing evidence reports `unknown` instead of false `succeeded`, with the exact zero-model ledger retained.
- Bridge Prolog/Python/Nim language experts into the canonical `MetaExpertComposer` under the caller-owned shared zero-model budget and cancellation/workspace-generation fence; late cancelled or stale output is rejected before evidence commit and `repair.apply` remains blocked at the typed effect boundary.

### zara-emacs 0.3.0
- Route editor control through the versioned `ZARA-EMACS/1` native bridge instead of per-operation Elisp templates.
- Add live session/buffer/window/command inspection using opaque IDs.
- Add bounded buffer reads plus revision-safe edit preview/apply/cancel/status and explicit save.
- Keep named workflows and compatibility open/daily/Magit/dashboard/chat operations on the same bridge.
- Fail closed on bridge version/operation/result mismatches.

### zara-emacs 0.2.0
- Use the full configured Org notes root as a bounded knowledge surface.
- Add Org QL queries for active shared agent memory and inventory/food state.
- Add structured daily inventory events for buy/receive/putaway/move/consume and related stock changes; manual adjustments require explicit add/remove direction.
- Add unresolved-event discovery and idempotent Org-roam inventory-item materialization by ITEM_KEY.
- Add provenance-bearing shared-memory assertion writes with supersession checks.
- Add fixed-template dashboard and native Zara-chat operations.
- Add operator-owned named editor workflows with a closed operation vocabulary, validation before execution, and exact failing-step errors.
