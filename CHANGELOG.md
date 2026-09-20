# Changelog

## Unreleased

### zara-expert
- Add provider-free PrologExpert, PythonExpert, and NimExpert adapters over canonical Dotfiles-owned expert sources.
- Route applicability, evidence, diagnostics, style rules, repair preview/verification, and explanation through host-issued registered-predicate authority with `max_model_calls=0`.
- Expose closed applicability/result schemas and canonical runtime symbols; `repair.apply` remains behind Zara's typed edit/effect authority with fresh postcondition verification.

### zara-emacs 0.2.0
- Use the full configured Org notes root as a bounded knowledge surface.
- Add Org QL queries for active shared agent memory and inventory/food state.
- Add structured daily inventory events for buy/receive/putaway/move/consume and related stock changes; manual adjustments require explicit add/remove direction.
- Add unresolved-event discovery and idempotent Org-roam inventory-item materialization by ITEM_KEY.
- Add provenance-bearing shared-memory assertion writes with supersession checks.
- Add fixed-template dashboard and native Zara-chat operations.
- Add operator-owned named editor workflows with a closed operation vocabulary, validation before execution, and exact failing-step errors.
