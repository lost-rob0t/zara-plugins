# Changelog

## Unreleased

### zara-emacs knowledge tooling (experimental)
- Add an opt-in `zara-emacs-kb` Nix package and check for boot-loaded Emacs documentation, deterministic Prolog facts, provenance and explicit coverage gaps.
- Add bounded read-only Prolog query helpers plus Python, Emacs ERT and SWI-Prolog fixtures. Full corpus coverage, live expert activation and voice control remain follow-up work.

### zara-emacs 0.2.0
- Use the full configured Org notes root as a bounded knowledge surface.
- Add Org QL queries for active shared agent memory and inventory/food state.
- Add structured daily inventory events for buy/receive/putaway/move/consume and related stock changes; manual adjustments require explicit add/remove direction.
- Add unresolved-event discovery and idempotent Org-roam inventory-item materialization by ITEM_KEY.
- Add provenance-bearing shared-memory assertion writes with supersession checks.
- Add fixed-template dashboard and native Zara-chat operations.
- Add operator-owned named editor workflows with a closed operation vocabulary, validation before execution, and exact failing-step errors.
