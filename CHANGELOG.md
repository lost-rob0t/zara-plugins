# Changelog

## Unreleased

### zara-music 0.1.0
- Add Prolog-first runtime commands for music search, recommendations, play, pause, volume, current-track favorites, and adding the current track to a playlist.
- Register the same command names in Zara's programmable runtime namespace and a portable Prolog tool catalog, keeping effect authority in the canonical runtime.
- Fail closed when current-track mutations have no active track and require explicit verified mutation evidence.

### zara-emacs 0.2.0
- Use the full configured Org notes root as a bounded knowledge surface.
- Add Org QL queries for active shared agent memory and inventory/food state.
- Add structured daily inventory events for buy/receive/putaway/move/consume and related stock changes; manual adjustments require explicit add/remove direction.
- Add unresolved-event discovery and idempotent Org-roam inventory-item materialization by ITEM_KEY.
- Add provenance-bearing shared-memory assertion writes with supersession checks.
- Add fixed-template dashboard and native Zara-chat operations.
- Add operator-owned named editor workflows with a closed operation vocabulary, validation before execution, and exact failing-step errors.
