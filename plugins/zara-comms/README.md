# zara-comms

Provider-neutral email/chat/message operations for Zara with one normalized public schema and explicit, verified sending.

Messages retain provider/account/conversation/message identity, sender/recipients, timezone-aware timestamps, bounded bodies, attachment metadata, read state, and reply identity. Attachment bytes are not exposed by the normalized listing surface.

## Tools

- `comms.status`
- `comms.search`
- `comms.get`
- `comms.draft`
- `comms.draft_reply`
- `comms.send`

Draft creation never sends. Recipient queries are resolved through the contacts boundary; ambiguous or unavailable identities fail before a provider action. Reply drafts preserve the original provider, account, thread, sender, and message identity.

`comms.send` is the only mutation. It requires a structured draft, records provider acknowledgement, then reads the resulting provider message. Rejection or missing/mismatched observed state returns `verification_failed`; process/HTTP success is not enough.

Provider OAuth/tokens remain outside Git and the Nix store. An unconfigured install reports `comms-provider-not-configured` instead of pretending to have messaging access. Tests use fake providers and a fake contacts resolver with no network or credentials. Zara Core remains authoritative for approval and authorization policy.
