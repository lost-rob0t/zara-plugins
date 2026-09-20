# zara-sysadmin

Typed Linux/NixOS diagnostics and bounded remediation for Zara.

This plugin deliberately does **not** expose a raw shell. A production backend must translate the typed operations into bounded systemd, journal, process/resource, network, and Nix observations/actions. Without such a backend, the service reports `system-backend-not-configured` and does not pretend work succeeded.

## Surface

Read/diagnostic tools:

- `sysadmin.status`
- `sysadmin.service.status`
- `sysadmin.service.diagnose`
- `sysadmin.service.port_diagnose`
- `sysadmin.journal`
- `sysadmin.processes`
- `sysadmin.resources`
- `sysadmin.network`
- `sysadmin.dns.diagnose`
- `sysadmin.nix.generations`
- `sysadmin.rules`

Explicit mutation tools:

- `sysadmin.service.action` — only `start`, `stop`, `restart`
- `sysadmin.nix.operation` — only `check`, `build`, `switch`

Mutations preserve before/action/after evidence. A backend accepting a request is **not** success: service changes are re-read and Nix switches are checked against generation evidence. Failed verification returns `verification_failed`.

## Expert-system rules

The canonical symbolic SysadminExpert rules are project-owned under
`lost-rob0t/dotfiles/.zara/experts/sysadmin/` (introduced by dotfiles#291).
This plugin keeps the typed system observation/remediation adapter surface; it must
not carry a second canonical Prolog rule corpus.

The current Python diagnosis path preserves the existing four deterministic chains
for compatibility until the canonical ZARA-EXPERT/1 composition adapter consumes
the dotfiles-owned expert. New symbolic rules belong in dotfiles, not here.

## Security boundary

Inputs and result counts are bounded. Unit names and Nix targets reject control characters. No privilege escalation, `sudo`, arbitrary command construction, shell snippets, eval, or unrestricted systemctl/Nix arguments are exposed. The configured backend is responsible for operating-system policy and timeouts; Zara Core remains responsible for normal tool authorization and approval.

Read-only diagnosis is the default surface. All state-changing operations are individually typed and allowlisted.

## Verification

The tests use a fake system backend only. They require no root access, systemd daemon, network, Nix store mutation, credentials, or host state.
