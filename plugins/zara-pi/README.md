# zara-pi

`zara-pi` is Zara's coding-agent bridge for Pi. This first slice provides a canonical-approval-gated Bash tool backed by Zara-owned tmux sessions plus honest Pi/tmux/Bash readiness for the Android/desktop coding surfaces tracked by `lost-rob0t/zara#1007`.

Pi itself already has a native `bash` tool and a JSONL RPC mode (`pi --mode rpc`). The selected architecture is to consume that machine interface and interpose Zara Core's canonical effect policy from `lost-rob0t/zara#887`; tmux is used for durable human-visible shell continuity, not as the agent protocol or an authorization mechanism.

## Current surface

- `pi.status` reports whether Pi, tmux, Bash, project-root policy, and the tmux bridge are available. It exposes no environment values, provider keys, or credentials.
- `pi.bash` sends one bounded Bash command into a Zara-owned tmux session. It is marked with Core's canonical `zara_requires_approval=true` metadata. The caller supplies a bounded invocation ID used only for correlation; it is not authority.
- `pi.tmux.ensure` creates or reuses a tmux session in the `zara-pi-*` namespace under an allowed project root. Existing sessions are reusable only when they carry Zara's private tmux owner option; a same-named human session is refused rather than adopted.
- `pi.tmux.capture` returns bounded, ANSI/control-sanitized pane output. With an invocation ID it verifies a plugin-generated nonce marker and returns `active`, `completed`, or `unknown`; a completed command includes the observed exit code.
- `pi.tmux.interrupt` checks the current persisted invocation identity before sending `Ctrl-C`. It reports `terminated_confirmed=false` because sending an interrupt is not proof the process tree exited.
- `pi.tmux.close` kills only a tmux session proven to carry Zara Pi's owner marker.

All tmux operations use fixed argv with `shell=False`. The shell command itself is intentionally interpreted by Bash inside the owned pane; that arbitrary-shell authority exists only behind the approval-gated `pi.bash` effect. This does **not** widen `zara-shell`, whose `shell.run` remains the separate constrained argv-only generic primitive.

The current plugin detects Pi but does not yet launch an unrestricted Pi RPC process: `pi.status` reports `pi_rpc_effect_adapter_ready=false`. The next `#839` slice replaces/interposes Pi's Bash/edit/write effect operations so Pi cannot execute those effects until Core #887 approves them (or Core's explicit local YOLO policy is active). Android `#1007` consumes this plugin for its Copilot/terminal integration; the Android client never executes the shell effect itself.

## Configuration

```toml
[plugins.zara-pi]
allowed_roots = ["~/Documents/Projects"]
pi = "pi"
tmux = "tmux"
bash = "bash"
max_command_bytes = 65536
max_capture_bytes = 65536
max_tmux_lines = 2000
operation_timeout_seconds = 5.0
```

`allowed_roots` is mandatory. With no roots configured the plugin loads but reports `pi-policy-not-configured` and every effect fails closed. Missing Pi is a degraded state while the Bash/tmux bridge can remain usable; missing tmux or Bash disables the bridge.

## Android / Termux direction

Pi's supported Android path is Termux. Zara Android should invoke the reviewed `zara-pi`/Core capability boundary rather than scraping or automating the Termux UI. Durable session IDs let the Code Editor detach and reattach after Activity/process recreation without replaying an already-started Bash effect. Project access remains scoped to roots selected/configured for the runtime.

## Security invariants

- no model/tool argument can set `approval=false`, `yolo=true`, an alternate tmux socket, or arbitrary tmux options;
- every effectful public tool is marked for Zara's canonical approval controller;
- cwd is canonicalized beneath configured roots before tmux creation;
- session and invocation IDs use closed grammars that cannot address arbitrary tmux panes/servers;
- Bash command and pane output are bounded;
- invocation completion uses a plugin-generated random nonce persisted in a tmux option and observed in captured output;
- stale invocation IDs cannot interrupt a newer command;
- same-named non-Zara sessions are never adopted;
- ordinary diagnostics do not expose command bodies, environment dumps, or provider secrets;
- `Ctrl-C` acknowledgement is never mislabeled as proven process termination.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-pi/test -t plugins/zara-pi/test
python3 scripts/validate-registry.py
nix flake check
```

Tests use deterministic fake tmux execution and temporary directories; they require no network, live Pi process, tmux server, Android device, credentials, or GUI.
