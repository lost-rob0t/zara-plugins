# zara-contacts

Provider-neutral contact identity and recipient resolution for Zara.

Contacts preserve stable IDs, display names and aliases, validated email/phone addresses, organization roles, provider handles, and source provenance with bounded confidence. Search and resolution never silently merge or guess ambiguous people.

## Tools

- `contacts.status`
- `contacts.search`
- `contacts.get`
- `contacts.resolve`
- `contacts.create`
- `contacts.update`

`contacts.resolve` requires an explicit channel such as `email`, `phone`, or a configured provider handle name. Multiple matching identities return `ambiguous` candidates without selecting a recipient. A unique person lacking the requested address returns `unavailable`.

Writes are explicit and preserve backend acknowledgement plus a fresh observed contact. A provider rejection or mismatched observed state returns `verification_failed`; HTTP/process success alone is never treated as proof.

Credentials and private provider configuration remain outside Git and the Nix store. Without a configured backend the plugin reports `contacts-backend-not-configured`. Tests use only a fake backend and require no network or live accounts. Zara Core remains responsible for normal authorization and approval policy.
