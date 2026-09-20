# zara-nix-expert

`zara-nix-expert` is the Zara product adapter for the reusable **NixExpert** symbolic expert.

## Ownership

The expert brain is not duplicated here. Canonical NixExpert rules, corpora, style policy, and tests belong in `lost-rob0t/dotfiles/.zara/experts/nix` under dotfiles #286/#292. Generic expert runtime semantics remain in `lost-rob0t/prolog-rlm` (#376/#503). This package owns only Zara lifecycle/discovery/tool adaptation.

## Pure-symbolic contract

The adapter exposes `nix.expert.descriptor` and `nix.expert.invoke`. Invocation is restricted to declared read-only operations (`parse`, flake/module/Home Manager inspection, style checking, and check-plan production) and crosses Zara Core's canonical cross-plugin capability boundary through `expert.invoke`.

Descriptors and requests follow the current `ZARA-EXPERT/1` contract from Zara #1233/#1273. Each invocation carries explicit request/activation identity, expected registry/runtime generations, a bounded deadline/result/output envelope, and `max_model_calls=0`. The adapter rejects unsupported operations, stale/malformed generation inputs, oversized/deep JSON, missing capability composition, non-mapping results, any result that does not prove `usage.model_calls == 0`, and any side-effect receipt returned from a read-only operation. Declared path inputs must also be non-empty and NUL-free before capability resolution. There is no provider, network, raw-Prolog-goal, subprocess, `nix eval`, build, or Home Manager fallback in this package.

Potential effects are descriptor metadata only: `nix.eval`, `nix.check`, `nix.build`, and `home-manager.switch`. Every operation shipped by this adapter currently declares `effects: []`. A future effectful operation must cross Zara's normal capability/approval/executor boundary and provide fresh postcondition evidence; this adapter never performs those effects during discovery or inspection.

The canonical source is pinned by `expert-source.lock.json` to the merged Dotfiles producer revision. The descriptor remains deliberately `unavailable` until the live canonical expert host activates that source; it does not fabricate registry or runtime availability.

## Dependency readiness

The canonical dotfiles NixExpert source is landed and pinned. Invocation still fails closed until the ZARA-EXPERT/1 registered-predicate host is installed/activated. Discovery remains passive and does not manufacture availability.

## Tests

`test/test_plugin.py` and `test/test_typed_boundary.py` prove passive discovery, canonical descriptor/request shape, capability composition, fixed registered operation names, bounded input and budgets, exact zero-model limits/results, typed input admission including invalid-path rejection before host dispatch, rejection of effectful/unknown operations, rejection of read-only effect leakage, and fail-closed behavior when the expert host is unavailable.
