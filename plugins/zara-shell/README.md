# zara-shell

`zara-shell` is Zara's deliberately narrow generic local execution primitive. It is not an unrestricted terminal and does not replace `zara-sysadmin`, `zara-coding`, or `zara-desktop`.

## Security contract

`shell.run` accepts an argv array only and always executes with `shell=False`. The first argv element must be explicitly allowlisted. The working directory must resolve beneath one of the configured roots. Runtime, stdin, stdout/stderr, and explicit environment sizes are bounded.

Child processes do not inherit the host environment. Model-supplied environment keys are **default-deny** and must also appear in the operator-owned `allowed_environment` list before execution. This keeps loader/interpreter controls such as `LD_PRELOAD` or `PYTHONPATH` from becoming an alternate arbitrary-execution path around the argv allowlist. Environment values are never exposed through `shell.status`.

The tool is marked with Zara Core's canonical `zara_requires_approval=true` LangChain tool metadata. Current Zara Core carries that marker into the existing principal-scoped `ToolApprovalController`; callers and model arguments cannot downgrade it. This plugin does not create a second approval channel.

When no allowlist/roots are configured, the service still loads but reports `shell-policy-not-configured` and execution fails closed.

## Configuration

```toml
[plugins.zara-shell]
allowed_programs = ["git", "nix"]
allowed_roots = ["~/Documents/Projects"]
# Optional. Omit or leave empty to deny every model-supplied environment key.
allowed_environment = ["LANG"]
max_runtime_seconds = 10.0
max_output_bytes = 65536
max_input_bytes = 65536
max_environment_bytes = 4096
```

Absolute program paths may be allowlisted. Bare program names are resolved without shell interpolation. Only exact environment names in `allowed_environment` may be supplied by a tool call. Higher-level plugins should prefer typed domain operations rather than passing arbitrary command strings through this primitive.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-shell/test -t plugins/zara-shell/test
python3 scripts/validate-registry.py
nix flake check
```

Tests use only local subprocesses under temporary roots and require no network or privileged host access.
