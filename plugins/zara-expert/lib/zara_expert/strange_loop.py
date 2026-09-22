from __future__ import annotations

import math
import re
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .domain import ExpertError, ExpertHost


_PREDICATE_RE = re.compile(r"^[a-z][a-zA-Z0-9_]{0,63}$")
_HOOK_STAGES = frozenset(
    {
        "configured",
        "before_tick",
        "after_tick",
        "error",
        "stopped",
    }
)


@dataclass(frozen=True)
class StrangeLoopConfig:
    """Fail-closed configuration for Zara's private symbolic RSI controller."""

    enabled: bool = False
    background: bool = True
    interval_seconds: float = 60.0
    max_iterations: int = 8
    max_candidates: int = 16
    min_improvement: float = 0.0
    sources: tuple[Path, ...] = ()
    tick_predicate: str = "strange_loop_tick"
    status_predicate: str = "strange_loop_status"

    @classmethod
    def from_mapping(
        cls,
        value: Mapping[str, Any] | None,
    ) -> "StrangeLoopConfig":
        if value is None:
            return cls()
        if not isinstance(value, Mapping):
            raise ExpertError("strange_loop configuration must be a mapping")

        allowed = {
            "enabled",
            "background",
            "interval_seconds",
            "max_iterations",
            "max_candidates",
            "min_improvement",
            "sources",
            "tick_predicate",
            "status_predicate",
        }
        unknown = set(value) - allowed
        if unknown:
            raise ExpertError(
                f"unknown strange_loop configuration key: {sorted(unknown)[0]!r}"
            )

        enabled = _boolean(value.get("enabled", False), "enabled")
        background = _boolean(value.get("background", True), "background")
        interval_seconds = _finite_number(
            value.get("interval_seconds", 60.0),
            "interval_seconds",
            minimum=0.25,
        )
        max_iterations = _positive_integer(
            value.get("max_iterations", 8),
            "max_iterations",
        )
        max_candidates = _positive_integer(
            value.get("max_candidates", 16),
            "max_candidates",
        )
        min_improvement = _finite_number(
            value.get("min_improvement", 0.0),
            "min_improvement",
            minimum=0.0,
        )
        tick_predicate = _predicate(
            value.get("tick_predicate", "strange_loop_tick"),
            "tick_predicate",
        )
        status_predicate = _predicate(
            value.get("status_predicate", "strange_loop_status"),
            "status_predicate",
        )
        sources = _sources(value.get("sources", ()))

        if enabled and not sources:
            raise ExpertError(
                "enabled strange_loop configuration requires trusted Prolog sources"
            )

        return cls(
            enabled=enabled,
            background=background,
            interval_seconds=interval_seconds,
            max_iterations=max_iterations,
            max_candidates=max_candidates,
            min_improvement=min_improvement,
            sources=sources,
            tick_predicate=tick_predicate,
            status_predicate=status_predicate,
        )


class StrangeLoopManager:
    """Own one private management worker over a trusted Prolog-RLM controller.

    The public expert.query host is deliberately not reused. The controller has
    its own non-exported ExpertHost, so untrusted callers cannot invoke the
    mutation tick by naming its namespace or predicate.

    The configured Prolog controller owns the evaluator/proposer/verifier hooks.
    The Python side only supplies bounded numeric policy and lifecycle.
    """

    NAMESPACE = "strange-loop"

    def __init__(
        self,
        host: ExpertHost,
        config: StrangeLoopConfig,
    ) -> None:
        if not isinstance(config, StrangeLoopConfig):
            raise TypeError("config must be StrangeLoopConfig")
        self._host = host
        self.config = config
        self._hooks: dict[str, list[Callable[[Mapping[str, Any]], Any]]] = {
            stage: [] for stage in _HOOK_STAGES
        }
        self._worker: Any = None
        self._registered = False
        self._tick_count = 0
        self._error_count = 0
        self._last_status = "disabled" if not config.enabled else "configured"
        self._lock = threading.RLock()

    def register_hook(
        self,
        stage: str,
        callback: Callable[[Mapping[str, Any]], Any],
    ) -> None:
        if stage not in _HOOK_STAGES:
            raise ExpertError(f"unknown strange-loop hook stage: {stage!r}")
        if not callable(callback):
            raise TypeError("strange-loop hook must be callable")
        with self._lock:
            self._hooks[stage].append(callback)

    def start(self, runtime: Any) -> None:
        if not self.config.enabled:
            return

        self._host.register(
            self.NAMESPACE,
            self.config.sources,
            predicates={
                self.config.tick_predicate: 3,
                self.config.status_predicate: 1,
            },
        )
        with self._lock:
            self._registered = True
            self._last_status = "ready"

        self._emit(
            "configured",
            {
                "enabled": True,
                "background": self.config.background,
                "source_count": len(self.config.sources),
                "max_iterations": self.config.max_iterations,
                "max_candidates": self.config.max_candidates,
                "min_improvement": self.config.min_improvement,
            },
        )

        if self.config.background:
            starter = getattr(runtime, "start_worker", None)
            if not callable(starter):
                self.stop()
                raise ExpertError(
                    "enabled background strange loop requires PluginRuntime.start_worker"
                )
            self._worker = starter("strange-loop", self._worker_main)

    def stop(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            request_stop = getattr(worker, "request_stop", None)
            if callable(request_stop):
                request_stop()

        if self._registered:
            self._host.clear_registrations()
        with self._lock:
            self._registered = False
            if self.config.enabled:
                self._last_status = "stopped"
        self._emit("stopped", {"status": self._last_status})

    def tick_once(self) -> dict[str, Any]:
        if not self.config.enabled:
            raise ExpertError("strange loop is disabled")
        with self._lock:
            if not self._registered:
                raise ExpertError("strange loop is not started")

        tick_number = self._tick_count + 1
        self._emit(
            "before_tick",
            {
                "tick": tick_number,
                "max_iterations": self.config.max_iterations,
                "max_candidates": self.config.max_candidates,
                "min_improvement": self.config.min_improvement,
            },
        )

        try:
            result = self._host.query(
                self.NAMESPACE,
                self.config.tick_predicate,
                [
                    self.config.max_iterations,
                    self.config.max_candidates,
                    self.config.min_improvement,
                ],
            )
        except Exception as exc:
            with self._lock:
                self._error_count += 1
                self._last_status = "error"
            event = {
                "tick": tick_number,
                "error_type": type(exc).__name__,
            }
            self._emit("error", event)
            if isinstance(exc, ExpertError):
                raise
            raise ExpertError(f"strange-loop tick failed: {type(exc).__name__}") from exc

        summary = _result_summary(result)
        with self._lock:
            self._tick_count = tick_number
            self._last_status = "ready"
        self._emit("after_tick", {"tick": tick_number, **summary})
        return result

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.config.enabled,
                "background": self.config.background if self.config.enabled else False,
                "status": self._last_status,
                "registered": self._registered,
                "tick_count": self._tick_count,
                "error_count": self._error_count,
                "source_count": len(self.config.sources),
                "max_iterations": self.config.max_iterations,
                "max_candidates": self.config.max_candidates,
                "min_improvement": self.config.min_improvement,
                "model_calls": 0,
            }

    def _worker_main(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set():
            try:
                self.tick_once()
            except ExpertError:
                pass
            if stop_event.wait(self.config.interval_seconds):
                break

    def _emit(self, stage: str, event: Mapping[str, Any]) -> None:
        with self._lock:
            callbacks = tuple(self._hooks[stage])
        safe_event = dict(event)
        for callback in callbacks:
            try:
                callback(safe_event)
            except Exception:
                continue


def _boolean(value: Any, field: str) -> bool:
    if type(value) is not bool:
        raise ExpertError(f"strange_loop {field} must be a boolean")
    return value


def _positive_integer(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ExpertError(f"strange_loop {field} must be a positive integer")
    return value


def _finite_number(
    value: Any,
    field: str,
    *,
    minimum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExpertError(f"strange_loop {field} must be a finite number")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise ExpertError(
            f"strange_loop {field} must be finite and >= {minimum}"
        )
    return number


def _predicate(value: Any, field: str) -> str:
    if not isinstance(value, str) or _PREDICATE_RE.fullmatch(value) is None:
        raise ExpertError(f"strange_loop {field} is not a valid predicate name")
    return value


def _sources(value: Any) -> tuple[Path, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ExpertError("strange_loop sources must be a list")

    paths: list[Path] = []
    for item in value:
        if not isinstance(item, (str, Path)):
            raise ExpertError("strange_loop sources entries must be paths")
        path = Path(item).expanduser().resolve()
        if path.suffix != ".pl":
            raise ExpertError("strange_loop sources must be Prolog .pl files")
        if not path.is_file():
            raise ExpertError(f"strange_loop source does not exist: {path}")
        paths.append(path)

    if len(set(paths)) != len(paths):
        raise ExpertError("strange_loop sources contain duplicates")
    return tuple(paths)


def _result_summary(result: Any) -> dict[str, Any]:
    if not isinstance(result, Mapping):
        return {"ok": False, "result_count": 0, "trace_count": 0}
    results = result.get("results")
    trace = result.get("trace")
    return {
        "ok": result.get("ok") is True,
        "result_count": len(results) if isinstance(results, list) else 0,
        "trace_count": len(trace) if isinstance(trace, list) else 0,
    }


__all__ = [
    "StrangeLoopConfig",
    "StrangeLoopManager",
]
