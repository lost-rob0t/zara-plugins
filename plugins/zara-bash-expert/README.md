# zara-bash-expert

`zara-bash-expert` is the Zara product adapter for the reusable **BashExpert** symbolic expert.

## Ownership

The expert brain is not duplicated here. Canonical BashExpert rules, corpora, style policy, and tests belong in `lost-rob0t/dotfiles/.zara/experts/bash` under dotfiles #287/#292. Generic expert runtime semantics remain in `lost-rob0t/prolog-rlm` (#376/#502). This package owns only Zara lifecycle/discovery/tool adaptation.

## Pure-symbolic contract

The adapter exposes `bash.expert.descriptor` and `bash.expert.invoke`. Invocation is restricted to declared read-only operations (`parse`, startup-file inspection, source-graph inspection, quoting diagnosis, style checking, and check-plan production) and crosses Zara Core's canonical cross-plugin capability boundary through `expert.invoke`.

Every request carries `ZARA-EXPERT/1`, `max_model_calls=0`, and `effect_policy=deny`. The adapter rejects unsupported operations, missing capability composition, malformed input, non-mapping results, and any result that does not prove `usage.model_calls == 0`. There is no provider, network, raw-Prolog-goal, `source`, shell/subprocess, or model fallback in this package.

Potential effects are descriptor metadata only: `bash.execute` and `filesystem.write`. A later effect must cross Zara's normal capability/approval/executor boundary and provide fresh postcondition evidence; this adapter never performs those effects during discovery or inspection.

## Dependency readiness

Until the canonical dotfiles BashExpert source and the ZARA-EXPERT/1 host adapter are installed/activated, invocation fails closed. Discovery remains passive and does not manufacture availability.

## Tests

`test/test_plugin.py` proves passive discovery, canonical capability composition, fixed registered operation names, zero-model limits/results, rejection of effectful/unknown operations, and fail-closed behavior when the expert host is unavailable.
