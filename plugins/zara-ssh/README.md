# zara-ssh

Bounded SSH/SFTP remote-file transport for Zara.

This plugin is deliberately **not** a remote shell. It provides typed host/file operations suitable for composition by other Zara plugins, including `zara-music`, while preserving Zara Core's canonical capability and approval boundaries.

## Surface

- `ssh.status`
- `ssh.hosts`
- `ssh.file.stat`
- `ssh.file.list`
- `ssh.file.fetch`

The plugin also registers the canonical programmable command symbols `ssh:hosts`, `ssh:file-stat`, `ssh:file-list`, and `ssh:file-fetch`. `prolog/zara_ssh_tools.pl` exposes matching portable facts so Prolog can reason about the same read/write capability names without becoming the effect executor.

`ssh.file.fetch` is approval-gated and succeeds only after the destination file is observed with the expected byte count and a computed SHA-256 digest.

## Configuration

```toml
[plugins.zara-ssh]
max_list_entries = 100

[plugins.zara-ssh.hosts.media]
hostname = "musicbox.example"
username = "zara"
port = 22
remote_roots = ["/srv/music"]
local_roots = ["/home/user/Music/imported"]
max_transfer_bytes = 4294967296
timeout_seconds = 15.0
known_hosts = "/home/user/.ssh/known_hosts"
identity_file = "/home/user/.ssh/id_ed25519"
```

`known_hosts` and `identity_file` are path references only. Their contents are never returned by Zara tools or projected into Prolog facts. If `known_hosts` is omitted, Paramiko uses the system/user host-key stores and still rejects unknown hosts. Missing host keys are never auto-added.

## Security and verification

- no command execution, shell strings, remote eval, port forwarding, or agent command surface;
- host aliases are configured, not caller-selected arbitrary network destinations;
- remote paths must stay beneath configured POSIX roots;
- local destinations must stay beneath configured local roots;
- existing destination files are never overwritten;
- remote file size is checked before transfer;
- transfer size is bounded per host;
- host-key verification is strict through Paramiko `RejectPolicy`;
- only key/agent authentication is supported by this first slice;
- transport exceptions are reduced to bounded non-secret `ssh-transport-failed` errors;
- successful fetches are independently verified from the local file.

Zara Music owns music semantics. Its portable Prolog catalog maps remote retrieval to `ssh.file.fetch`; the assistant/runtime executes that approval-gated SSH effect as its own canonical tool step. Do not import this plugin's private Python modules or bypass the SSH approval policy.

## Verification

```sh
python3 -m unittest discover -s plugins/zara-ssh/test -t plugins/zara-ssh/test
python3 scripts/validate-registry.py
nix flake check
```
