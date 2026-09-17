# zara-prolog 0.1.0

First-class operator Prolog as a Zara Plugin API v1 service: `prolog.status`,
`prolog.query`, `prolog.catalog`, and `prolog.reload`. Uses the canonical
`zara.prolog_engine.PrologEngine`, not a parallel PySWIP runtime or Prolog-RLM.

On startup, the shipped executable `lib/zara_prolog/config.pl` is copied only
when absent to `$XDG_CONFIG_HOME/zarathushtra/plugins/zara-prolog/config.pl`
(default `~/.config/zarathushtra/plugins/zara-prolog/config.pl`) and consulted.
The sample defines `prolog_mode(symbolic)` and an executable CLPFD example.
That fact describes this plugin configuration; it does not replace Zara's
LangGraph conversation backend or add a new desktop/Android UI mode.

```prolog
:- module(zara_prolog_user, [prolog_mode/1, example/2]).
:- use_module(library(clpfd)).
prolog_mode(symbolic).
example(square, X-Y) :- between(1,10,X), Y #= X*X.
```

Query `example(square, 3-Y)` using `prolog.query`; bindings are rendered as
Prolog strings inside structured JSON. Queries distinguish success from
logical failure. The catalogue returns at most 64 local predicate names and
arities. This is a bounded listing, not a claim that every predicate was shown.

Both arbitrary query and config reload carry Zara's
`zara_requires_approval` metadata. Approval remains owned by Zara's existing
tool gate. Config is real code: add predicates, import API-client modules and
perform authorized operator operations. The example is not a constrained
key/value parser. Loading config executes directives immediately.

This is **not a sandbox**. Queries have cooperative two-second and one-million
inference budgets, 8,192 input characters, at most 64 solutions, 32 variables
and 4,096 characters per rendered binding. These do not isolate native code,
prevent `halt/0`, or make hostile Prolog safe. Run only trusted operator code.
Session state shares the process-wide Prolog runtime and is not tenant-isolated.

`prolog.reload` reconsults the operator file without overwriting it. Reload is
not transactional; previous side effects cannot be rolled back. Stop/start
does not erase arbitrary global Prolog state. An unavailable engine is reported
explicitly rather than masquerading as a successful empty query.

The companion `zara-policy` service supplies the output-quality KB. Its own
private `config.pl` loads the bundled default rules automatically. The example
startup profile in `profiles/prolog-policy/config.toml` autoloads both plugins;
merge it with your existing configuration after installing their entrypoints.
A Nix build exposes the standard registry runtime layout; it does not by itself
activate services or edit your live config.

```sh
python3 -m unittest discover -s plugins/zara-prolog/test -t plugins/zara-prolog/test
ZARA_REQUIRE_SWIPL=1 python3 -m unittest discover -s plugins/zara-prolog/test -t plugins/zara-prolog/test
```

No native Android integration is included in this version. License:
GPL-3.0-or-later.
