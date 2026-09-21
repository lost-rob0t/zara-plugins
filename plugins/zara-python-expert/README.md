# zara-python-expert

`zara-python-expert` is the Zara product adapter for **PythonExpert**. Reusable semantics stay upstream in `lost-rob0t/prolog-rlm#498`; the canonical deterministic brain is pinned from `lost-rob0t/dotfiles/.zara/experts/python` by `expert-source.lock.json`.

The package is a leaf consumer of Zara's existing `expert.invoke` capability. It does not own an expert registry, scheduler, permission system, provider runtime, history store, or effect executor. Discovery is passive. Invocation preserves Core-owned activation/cancellation/generation/budget authority and requires the returned usage envelope to be exactly `{"model_calls": 0}` with empty effect receipts.

It exposes the canonical `match`, `inspect`, `diagnose`, `repair.preview`, `repair.verify`, `style.rules`, and `explain` schemas. Actual edits are not implemented here; they remain behind Zara's typed capability/approval/effect path and require fresh postcondition evidence.

Provider credentials are neither read nor required. Any missing host, malformed input/result, stale generation, model usage, or effect receipt fails closed.
