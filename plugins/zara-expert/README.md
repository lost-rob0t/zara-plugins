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

The base Lisp adapter maps structural check, diagnosis, missing-parenthesis repair preview, repair verification, style lookup, and explanation to fixed registered predicates. Dialect adapters may perform dialect-specific verification, but Common Lisp and Emacs Lisp **do not directly dispatch missing-paren preview through their own namespace**: Prolog-RLM #496/#497 require that repair proposal to delegate to `zara:expert/lisp`.

`LispFamilyCompositionInvoker` is the downstream bridge for that delegation. When it is run by `MetaExpertComposer`, a Common Lisp or Emacs Lisp `repair.preview` becomes a canonical child invocation of `zara:expert/lisp` under the exact same caller-owned `SharedSymbolicBudget` and cancellation/workspace-generation fence. The bridge creates no registry, scheduler, provider runtime, or permission surface. Direct dialect dispatch through `invoke_lisp_operation(...)` still fails closed, so callers cannot bypass canonical composition or reset the budget. Public input is limited to inert `arguments`; caller-authored predicate/goal selectors are rejected before the expert host is reached.

`repair.apply` is intentionally **not** a Prolog predicate. Its public ZARA-EXPERT/1 operation schema declares a filesystem-write effect and requires a repair proposal, expected preimage, and source generation. The expert host and composition bridge both refuse to apply the edit. Application must cross Zara's canonical typed edit/effect boundary and only succeeds after fresh postcondition evidence verifies the repaired structure. Until that capability is composed, `repair.apply` fails closed rather than writing files itself.

## Verification predicates

Domain packages may expose only predicates registered by trusted construction-time code. Lisp-family adapters privately bind `can_handle/2`, `structural_check/2`, `structural_diagnose/2`, `preview_repair/3`, `verify_repair/3`, `style_rules/2`, and `explain_decision/2`. Backend evidence is returned as structured data; a model claim is never treated as proof.

## Tests

```sh
python3 -m unittest discover -s plugins/zara-expert/test -t plugins/zara-expert/test
python3 scripts/validate-registry.py
nix flake check
```
