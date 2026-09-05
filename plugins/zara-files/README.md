# zara-files

Structured local-file operations confined to operator-configured roots.

## Configuration

```toml
[plugins.zara-files]
roots = ["~/Documents", "~/Pictures"]
max_read_bytes = 65536
max_results = 64
```

Roots are assigned opaque `root-0`, `root-1`, ... identifiers in tool output so normal results do not dump configured absolute host paths. With no roots configured the service reports `file-roots-not-configured` instead of gaining ambient filesystem access.

## Surface

- `files.status`
- `files.search`
- `files.metadata`
- `files.read_text`
- `files.create_text`
- `files.copy`
- `files.move`
- `files.rename`
- `files.delete`
- `files.semantic_search`

Semantic search is an optional adapter boundary; without an index it returns an explicit unavailable result.

## Filesystem threat model

Every public path is relative to a configured root. Absolute paths and `..` traversal are rejected. Configured roots themselves may not be symlinks. Existing path components are inspected without following symlinks; searches skip symlink files/directories; destination parent components may not be symlinks. Mutations never overwrite existing destinations. Directory deletion is intentionally absent from v1. Binary/non-UTF-8 files are metadata-first rather than decoded heuristically.

Reads, writes, result counts, patterns, paths, and tool arguments are bounded. The plugin does not expose a generic shell, arbitrary filesystem root, implicit recursive delete, or hidden overwrite flag. Zara Core remains responsible for its normal authorization/approval policy for mutations.

## Verification

Tests use temporary directories only and require no network, credentials, GUI, or operator filesystem state. The repository-wide generated compatibility gate validates the service against the pinned supported Zara API when published.
