# Changelog

## Unreleased

### zara-ssh 0.1.0
- Add typed SSH/SFTP host discovery, remote stat/list, and approval-gated file fetch commands with matching portable Prolog capability facts.
- Confine remote and local paths to configured roots, reject unknown hosts through strict host-key verification, and never expose key material through tool results.
- Verify fetched files by observed byte count and SHA-256 before reporting success; existing local destinations are never overwritten.

### zara-emacs 0.2.0
- Use the full configured Org notes root as a bounded knowledge surface.
- Add Org QL queries for active shared agent memory and inventory/food state.
- Add structured daily inventory events for buy/receive/putaway/move/consume and related stock changes; manual adjustments require explicit add/remove direction.
- Add unresolved-event discovery and idempotent Org-roam inventory-item materialization by ITEM_KEY.
- Add provenance-bearing shared-memory assertion writes with supersession checks.
- Add fixed-template dashboard and native Zara-chat operations.
- Add operator-owned named editor workflows with a closed operation vocabulary, validation before execution, and exact failing-step errors.
