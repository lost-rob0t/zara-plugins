# Changelog

## Unreleased

### zara-expert
- Add zero-model Zara adapters for canonical PrologExpert, PythonExpert, and NimExpert packages without duplicating their dotfiles-owned expert definitions.
- Expose closed applicability/inspection/diagnostic/style/explanation operations with source/digest evidence and fixed safe Prolog predicates.
- Propagate per-invocation timeout, result-count, and output-byte budgets through the existing expert host/backend while rejecting nonzero model-call budgets.

### zara-emacs 0.2.0
- Use the full configured Org notes root as a bounded knowledge surface.
- Add Org QL queries for active shared agent memory and inventory/food state.
- Add structured daily inventory events for buy/receive/putaway/move/consume and related stock changes; manual adjustments require explicit add/remove direction.
- Add unresolved-event discovery and idempotent Org-roam inventory-item materialization by ITEM_KEY.
- Add provenance-bearing shared-memory assertion writes with supersession checks.
- Add fixed-template dashboard and native Zara-chat operations.
- Add operator-owned named editor workflows with a closed operation vocabulary, validation before execution, and exact failing-step errors.
