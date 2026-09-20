# Emacs documentation knowledge package — experimental bootstrap

Implementation slice for `zara-plugins#857`, under `zara#1239`.
The existing service plugin's tools, API and version are unchanged.

## Implemented in this slice

`export.el` extracts raw documentation for boot-loaded functions, interactive
commands, variables and faces from a clean `emacs -Q --batch` process. It does
not export variable values, substitute runtime keybindings, load private init,
start a microphone, or deliberately require all installed packages. Registered
autoload docstrings can be observed without executing their library.

`emacs_kb.py` validates a closed UTF-8 JSONL schema and emits deterministic
`corpus.pl` and `manifest.json`. Corpus identity hashes normalized metadata and
sorted symbol-role rows; individual documentation records carry SHA-256 digests.
Duplicate roles, duplicate JSON keys, unknown fields, malformed types and
resource-limit violations are errors. The compiler quotes data as Prolog atoms;
documentation never supplies predicate names or executable clauses. The fixed
module wrapper enables SWI character escapes; an all-undocumented corpus gets
a fixed failing documentation relation, not an undefined predicate.

`expert.pl` supplies local read-only `describe/4`, `commands/2` and `search/3`
helpers. These are not yet registered Zara tools or a `ZARA-EXPERT/1` activation
adapter. The package does not grant command execution permissions. In
particular, `interactive=true` is not evidence that a command is safe to invoke.

## Build and inspect

From this repository on the implementation branch:

```sh
nix build .#zara-emacs-kb --print-build-logs
nix build .#checks.x86_64-linux.zara-emacs-kb --print-build-logs
cat result/share/zara/emacs-kb/manifest.json
swipl -q -f none -s result/share/zara/emacs-kb/expert.pl
```

At the Prolog prompt:

```prolog
describe('forward-char', function, Text, Evidence).
commands(10, Matches).
search('window', 8, Matches).
```

The root flake's existing locked nixpkgs supplies Emacs, Python and SWI-Prolog.
The auxiliary package/check is exposed on the existing x86_64-linux and
aarch64-linux flake systems. It is intentionally not added to the default
plugin environment: consumers opt into a KB artifact. No registry entry or
plugin dependency/version change is required for this build-only addition.

The derivation requires actual ERT and SWI tests, a hostile-documentation
round-trip, and two fresh extraction runs with identical compiled outputs.
A build failure is not skipped. The ordinary Python suite needs no Emacs or
network; it tests only the compiler, not actual Emacs extraction or reasoning.

```sh
python3 -m unittest discover -s plugins/zara-emacs/test -p test_kb.py -v
```

## Fact ABI, schema 1

```prolog
emacs_corpus(CorpusId, EmacsVersion, SourceId, Profile).
emacs_symbol(CorpusId, Name, Kind, Interactive, LibraryHint, DocumentationState).
emacs_documentation(CorpusId, Name, Kind, Text, DocumentationSha256).
```

`Kind` is `function`, `variable` or `face`; command status is a separate boolean.
A symbol may have several roles. A missing doc is JSON null / `undocumented`,
not an empty string. `LibraryHint` is only a filename hint, not a proven source
location. `SourceId` identifies the pinned Emacs output. The build includes
GNU Emacs's COPYING alongside the extracted corpus.

Limits: 64 MiB input, 1 MiB JSONL record, 100,000 symbol roles, 256 KiB per doc,
128 MiB generated facts. Helpers return at most 100 search/command entries;
search inputs are 1–256 characters. A future host adapter must also apply its
existing deadline, total response-byte and capability limits. These local
helpers do not implement host isolation, cancellation or activation.

## Explicit coverage gaps

This is **not all of Emacs**. The manifest reports
`complete_emacs_coverage=false` and separately counts documented/undocumented
symbol roles. The `core-loaded` profile includes core support libraries needed
by extraction, not every definition on `load-path`.

`#857` remains open for Info manuals, split/compressed manual inventories,
source declarations and unloaded packages, Custom metadata, hooks, references,
per-package provenance and full declared-source reconciliation. A build being
green cannot close those coverage gaps.

Live buffers, user command remaps, active minor-mode maps, private configuration
and custom package state belong to an opt-in **session overlay**, not this
public Nix package. `zara#1245` owns native control and observations;
`zara#1248` owns voice input. Those consume the same canonical Zara runtime,
expert host and operation authority. No voice/editor integration is shipped
merely by building this corpus.

## References

GNU Emacs Lisp Reference Manual, Accessing Documentation:
https://www.gnu.org/software/emacs/manual/html_node/elisp/Accessing-Documentation.html

SWI-Prolog quoted-atom character escapes:
https://www.swi-prolog.org/pldoc/man?section=syntax

Repository governance and integration contracts: `AGENTS.md`,
`plugins/zara-expert/README.md`, `zara#986`, `zara#1233` and `zara#1235`.
