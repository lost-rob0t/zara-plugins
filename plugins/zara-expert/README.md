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

Each adapter publishes a canonical `ZARA-EXPERT/1` descriptor into Zara's programmable symbol registry as `zara:expert/lisp`, `zara:expert/common-lisp`, or `zara:expert/emacs-lisp`. The public descriptor contains only the portable expert identity, schemas, lifecycle metadata, effect classes, fail-closed fallback policy, delegation policy, and finite resource limits. **Private Prolog predicate names and arities are not serialized into the public descriptor.** They stay bound inside trusted adapter construction through the registered-predicate capability boundary.

All three descriptors are pure symbolic and pin `max_model_calls=0`; `model_inference` is not an admitted effect. Missing canonical source is represented as `availability=absent` with `unavailable_reason=source-unavailable`, never as a provider/model fallback. Common Lisp and Emacs Lisp declare child delegation so composition can flow through Zara's canonical expert contract/shared-budget owner rather than a plugin-local scheduler. The plugin deliberately exports no `expert.lisp_invoke` or `expert.lisp_descriptors` tool surface; discovery, activation, generation fencing, cancellation, budgets, and invocation remain owned by ZARA-EXPERT/1.

### Core contract dependency

These adapters deliberately do not duplicate Core's invocation or budget logic. Pure-symbolic acceptance therefore depends on the canonical Zara registry preserving two host-owned invariants at the boundary:

- the reserved `expert_operation` discriminator must never be admitted as user-declared operation input; the host-selected operation is trusted metadata only;
- caller limits may only narrow descriptor/host ceilings. In particular, an expert descriptor with `resource_limits.max_model_calls=0` must remain zero-model even when a caller presents a larger `max_model_calls` value.

If either invariant is unavailable in the active Zara Core contract, the Lisp-family integration is not accepted as pure-symbolic and must stay fail-closed rather than adding a plugin-local dispatcher or accounting shim.

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

The base Lisp adapter maps structural check, diagnosis, missing-parenthesis repair preview, repair verification, style lookup, and explanation to fixed registered predicates. Dialect adapters may perform dialect-specific verification, but Common Lisp and Emacs Lisp **do not directly dispatch missing-paren preview through their own namespace**: Prolog-RLM #496/#497 require that repair proposal to delegate to `zara:expert/lisp`. Until Zara's canonical expert composition path can carry that child invocation with the caller's remaining shared budget, dialect `repair.preview` fails closed. This package contains no replacement parser or plugin-local delegation scheduler.

`repair.apply` is intentionally **not** a Prolog predicate. Its public ZARA-EXPERT/1 operation schema declares a filesystem-write effect and requires a repair proposal, expected preimage, and source generation. The expert host itself still refuses to apply the edit. Application must cross Zara's canonical typed edit/effect boundary and only succeeds after fresh postcondition evidence verifies the repaired structure. Until that capability is composed, `repair.apply` fails closed rather than writing files itself.

## Verification predicates

Domain packages may expose only predicates registered by trusted construction-time code. Lisp-family adapters privately bind `can_handle/2`, `structural_check/2`, `structural_diagnose/2`, `preview_repair/3`, `verify_repair/3`, `style_rules/2`, and `explain_decision/2`. Backend evidence is returned as structured data; a model claim is never treated as proof.

## Tests

```sh
python3 -m unittest discover -s plugins/zara-expert/test -t plugins/zara-expert/test
python3 scripts/validate-registry.py
nix flake check
```
