# Emacs expert KB

This directory contains the source for Zara's generated Emacs expert.

`export-emacs-kb.el` is run by Nix against the exact Emacs package selected by
`flake.nix`. The result is a data-only `emacs-kb.pl` containing facts from
Emacs' own self-documenting runtime.

The generated facts include:

- Emacs version/build provenance
- interactive commands
- functions
- variables
- documentation strings
- source/library provenance
- active key bindings

`rules.pl` adds small reusable predicates for command/function/variable lookup
and documentation search. Execution is deliberately separate: the expert can
recommend canonical command symbols, but Zara may only execute commands exposed
through `emacs.command_catalog` / `emacs.invoke_command`.

Build:

```sh
nix build .#zara-emacs-expert
ls result/share/zara/experts/emacs
```

The intended runtime consumer is the existing `zara-expert` protocol.
