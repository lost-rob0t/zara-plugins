# zara-github

Typed GitHub provider for Zara. It keeps GitHub HTTP semantics out of Zara core and exposes bounded PR, issue, check, review, repository, commit-status, comment, and verified merge operations through Zara's normal service-plugin tool boundary.

## Configuration

Configure the plugin under Zara's plugin configuration for `zara-github`.

- `owner`: GitHub login used by `github.pr.latest`.
- `api_base`: defaults to `https://api.github.com`; HTTPS is required.
- `timeout_seconds`: 0.1–120 seconds.
- `max_response_bytes`: 1 KiB–8 MiB.
- `max_results`: 1–100.
- `token_file`: optional mode-0600 file containing the token.

`ZARA_GITHUB_TOKEN` overrides configured token material. `ZARA_GITHUB_OWNER` may supply the default owner. Tokens are sent only as authorization headers and are never returned by tools or included in provider errors.

## Tool surface

Read operations: `github.pr.latest`, `github.pr.list`, `github.pr.get`, `github.pr.diff`, `github.pr.checks`, `github.pr.reviews`, `github.issue.list`, `github.issue.get`, `github.repo.get`, and `github.commit.status`.

Mutations: `github.pr.merge`, `github.issue.create`, `github.issue.update`, and `github.pr.comment`. Zara remains responsible for its canonical approval/capability policy before mutation tools execute.

## Verified merge semantics

`github.pr.merge` resolves the exact PR and current head SHA, rejects drafts and non-mergeable state, requires current-head check runs to be completed and conclusively successful, rejects blocking `CHANGES_REQUESTED` reviews, sends the expected head SHA to GitHub's merge endpoint, requires a positive provider acknowledgement, then re-fetches the PR and verifies the same head and observed merge commit. A 2xx response alone is never treated as proof of success.

Skipped, cancelled, pending, stale, missing, failing, and inconclusive check state fails closed. The v1 provider has no arbitrary URL/request tool.

## Tests

```sh
python3 -m unittest discover -s plugins/zara-github/test -t plugins/zara-github/test
python3 scripts/validate-registry.py
nix flake check
```

Tests use fake HTTP responses and require no network or credentials.
