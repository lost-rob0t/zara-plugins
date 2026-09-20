# zara-nix-expert

`zara-nix-expert` is the Zara product adapter for the reusable **NixExpert** symbolic expert.

## Ownership

The expert brain is not duplicated here. Canonical NixExpert rules, corpora, style policy, and tests belong in `lost-rob0t/dotfiles/.zara/experts/nix` under dotfiles #286/#292. Generic expert runtime semantics remain in `lost-rob0t/prolog-rlm` (#376/#503). This package owns only Zara lifecycle/discovery/tool adaptation.

## Pure-symbolic contract

The adapter exposes `nix.expert.descriptor` and `nix.expert.invoke`. Invocation is restricted to declared read-only operations (`parse`, flake/module/Home Manager inspection, style checking, and check-plan production) and crosses Zara Core's canonical cross-plugin capability boundary through `expert.invoke`.

Every request carries `ZARA-EXPERT/1`, `max_model_calls=0`, and `effect_policy=deny`. The adapter rejects unsupported operations, missing capability composition, malformed input, non-mapping results, and any result that does not prove `usage.model_calls == 0`. There is no provider, network, raw-Prolog-goal, subprocess, `nix eval`, build, or Home Manager fallback in this package.

Potential effects are descriptor metadata only: `nix.eval`, `nix.check`, `nix.build`, and `home-manager.switch`. A later effect must cross Zara's normal capability/approval/executor boundary and provide fresh postcondition evidence; this adapter never performs those effects during discovery or inspection.

## Dependency readiness

Until the canonical dotfiles NixExpert source and the ZARA-EXPERT/1 host adapter are installed/activated, invocation fails closed. Discovery remains passive and does not manufacture availability.

## Tests

`test/test_plugin.py` proves passive discovery, canonical capability composition, fixed registered operation names, zero-model limits/results, rejection of effectful/unknown operations, and fail-closed behavior when the expert host is unavailable.
