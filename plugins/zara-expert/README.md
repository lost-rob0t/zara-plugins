# zara-expert

`zara-expert` is the reusable bounded Prolog expert-system host for Zara plugins.

It keeps knowledge bases and mutable facts isolated by plugin namespace, separates session facts from persistent facts, admits only host-registered predicate capabilities, forwards hard query/result limits, and returns structured query/explanation evidence.

## Runtime model

The plugin is a Zara API v1 service plugin. Mutable state lives under `$XDG_DATA_HOME/zarathushtra/zara-expert` by default, never in the immutable Nix package. A backend can be injected by a host integration; when no SWI-Prolog backend is configured the service reports `unavailable` and query/explain operations fail explicitly instead of pretending reasoning succeeded.

Trusted construction-time code registers a namespace, its KB paths, and an explicit predicate-name/arity map through `ExpertHost.register(..., predicates=...)`. Public calls choose only one registered predicate plus structured inert arguments. Registration is deliberately not a Zara tool. Raw Prolog goals, module-qualified calls, directives, meta-calls, and arbitrary built-ins never become public execution authority.

## Safe operations

- bounded registered-predicate `query` and `explain` calls;
- scalar/variable argument descriptors that are encoded as data;
- ground-fact `assert_fact` and idempotent `retract_fact`;
- separate session and persistent state files;
- namespace validation and atomic state writes;
- explicit backend failure propagation.

The backend receives an opaque host-issued predicate capability rather than a caller-authored goal. String arguments that resemble Prolog remain quoted data. SWI is launched with `shell=False` and existing timeout/output bounds remain in force.

## Lisp-family adapters

The package also contains the Zara-owned adapters for `LispExpert`, `CommonLispExpert`, and `EmacsLispExpert` tracked by #860. The reusable parser/reader/style brains are **not** copied here: canonical expert source is owned by `lost-rob0t/dotfiles#292` under `.zara/experts/`, with generic expert semantics tracked by Prolog-RLM #494/#496/#497.

Each adapter publishes a `ZARA-EXPERT/1` descriptor into Zara's canonical programmable symbol registry as `zara:expert/lisp`, `zara:expert/common-lisp`, or `zara:expert/emacs-lisp`. Descriptors declare symbolic-only operation bindings and `max_model_calls=0`; provider/model/remote fallback is disabled. The adapter maps structural check, diagnosis, missing-parenthesis repair preview, repair verification, style lookup, and explanation to fixed registered predicates. It contains no Lisp parser implementation.

Canonical source files are opt-in through trusted plugin configuration:

```yaml
lisp_family_sources:
  lisp:
    - /path/to/.zara/experts/lisp/expert.pl
  common-lisp:
    - /path/to/.zara/experts/common-lisp/expert.pl
  emacs-lisp:
    - /path/to/.zara/experts/emacs-lisp/expert.pl
```

Absent source stays explicitly `source-unavailable`; there is no provider fallback. `repair.apply` is intentionally **not** a Prolog predicate. The expert may produce/verify a deterministic repair proposal, but applying it must cross Zara's canonical typed edit/effect boundary with expected-preimage authority and fresh postcondition verification. Until that capability is composed, `repair.apply` fails closed rather than writing files itself.

## Verification predicates

Domain packages may expose only predicates registered by trusted construction-time code. Lisp-family adapters currently bind `can_handle/2`, `structural_check/2`, `structural_diagnose/2`, `preview_repair/3`, `verify_repair/3`, `style_rules/2`, and `explain_decision/2`. Backend evidence is returned as structured data; a model claim is never treated as proof.

## Tests

```sh
python3 -m unittest discover -s plugins/zara-expert/test -t plugins/zara-expert/test
python3 scripts/validate-registry.py
nix flake check
```
