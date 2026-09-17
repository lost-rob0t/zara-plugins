"""Executable Prolog final-answer advice using Zara's canonical runtime."""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import threading
import tomllib
from typing import Any

from zara.plugins.api import PluginMetadata, ServicePlugin


class PolicyPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-policy", version="0.1.0",
        description="Executable Prolog final-answer matching with bounded model advice",
    )

    def __init__(self) -> None:
        self._active = False
        self._started = False
        self._loaded_engine = None
        self._load_lock = threading.Lock()
        self._rules: Path | None = None
        self._max_revisions = 2

    def start(self, runtime: Any) -> None:
        if self._started:
            raise RuntimeError("zara-policy instance has already started")
        root = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        root = root.expanduser() / "zarathushtra/plugins/zara-policy"
        rules = root / "policy.pl"
        if not rules.is_file() or not 0 < rules.stat().st_size <= 1048576:
            raise RuntimeError("zara-policy requires a nonempty private policy.pl of at most 1 MiB")
        settings_path = root / "config.toml"
        settings = {}
        if settings_path.exists():
            if settings_path.stat().st_size > 4096:
                raise ValueError("zara-policy config.toml exceeds 4096 bytes")
            with settings_path.open("rb") as handle:
                settings = tomllib.load(handle)
        if set(settings) - {"max_revisions"}:
            raise ValueError("unknown zara-policy private setting")
        revisions = settings.get("max_revisions", 2)
        if type(revisions) is not int or not 0 <= revisions <= 3:
            raise ValueError("max_revisions must be an integer from 0 to 3")
        self._rules = rules
        self._max_revisions = revisions
        runtime.register_agent_loop_advice("around", 100, self._around)
        self._started = True
        self._active = True

    def stop(self) -> None:
        self._active = False

    def _load_rules(self, engine: Any) -> None:
        if not callable(getattr(engine, "consult", None)) or not callable(getattr(engine, "query_once", None)):
            raise RuntimeError("zara-policy requires the canonical Prolog engine")
        with self._load_lock:
            if not self._active:
                raise RuntimeError("zara-policy is stopped")
            if self._loaded_engine is engine:
                return
            if self._loaded_engine is not None:
                raise RuntimeError("restart zara-policy after changing the canonical engine")
            try:
                engine.consult(self._rules)
            except Exception:
                raise RuntimeError("zara-policy failed to load its trusted Prolog rules") from None
            self._loaded_engine = engine

    async def _around(
        self, continuation: Any, model: Any, registry: Any, state: dict[str, Any], **kwargs: Any,
    ) -> dict[str, Any]:
        if not self._active:
            raise RuntimeError("zara-policy is stopped")
        if state.get("backend") == "prolog" or model is None:
            return await continuation(model, registry, state, **kwargs)
        try:
            from zara.agent.output_policy import AdvisedModel, PrologPolicy
        except ImportError:
            raise RuntimeError("zara-policy requires Zara's native output-policy core support") from None
        engine = getattr(registry, "prolog_engine", None)
        await asyncio.to_thread(self._load_rules, engine)
        context = {
            "principal_id": kwargs.get("principal_id", "local"),
            "turn_id": state.get("turn_id") or "",
            "conversation_id": state.get("conversation_id") or "",
        }
        policy = PrologPolicy(engine, context)
        advised = AdvisedModel(model, policy.evaluate, max_revisions=self._max_revisions)
        return await continuation(advised, registry, state, **kwargs)


def create_plugin() -> PolicyPlugin:
    return PolicyPlugin()
