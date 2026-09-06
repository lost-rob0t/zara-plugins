from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import os
import queue
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType, SimpleNamespace


@contextmanager
def temporary_runtime_environment(home: Path):
    home = home.resolve()
    locations = {
        "HOME": home,
        "XDG_CONFIG_HOME": home / ".config",
        "XDG_DATA_HOME": home / ".local" / "share",
        "XDG_CACHE_HOME": home / ".cache",
        "XDG_STATE_HOME": home / ".local" / "state",
    }
    previous = {name: os.environ.get(name) for name in locations}
    try:
        for name, path in locations.items():
            path.mkdir(parents=True, exist_ok=True)
            os.environ[name] = str(path)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


@contextmanager
def fake_dependency_environment(plugin_name: str):
    live_dependency_environment = {
        "zara-avatar": ("ZARA_AVATAR_RENDERER",),
        "zara-discord": ("ZARA_DISCORD_TOKEN",),
        "zara-github": ("ZARA_GITHUB_TOKEN",),
        "zara-knowledge": ("BRAVE_SEARCH_API_KEY",),
        "zara-starintel-server": (
            "ZARA_STARINTEL_URL",
            "ZARA_STARINTEL_API_KEY",
            "ZARA_STARINTEL_API_KEY_FILE",
            "ZARA_STARINTEL_BOOTSTRAP_SECRET",
            "ZARA_STARINTEL_BOOTSTRAP_SECRET_FILE",
        ),
    }
    removed = live_dependency_environment.get(plugin_name, ())
    previous = {name: os.environ.get(name) for name in removed}
    try:
        for name in removed:
            os.environ.pop(name, None)
        yield
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


class CompatibilitySubscription:
    def __init__(self) -> None:
        self.closed = False

    def get(self, timeout=None):
        raise queue.Empty

    def close(self) -> None:
        self.closed = True


class CompatibilityWorker:
    def __init__(self, name: str, target) -> None:
        self.name = name
        self.stop_event = threading.Event()
        self.error: Exception | None = None

        def run() -> None:
            try:
                target(self.stop_event)
            except Exception as error:
                self.error = error

        self._thread = threading.Thread(
            target=run,
            name=f"zara-plugin-{name}",
            daemon=True,
        )

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._thread.start()

    def request_stop(self) -> None:
        self.stop_event.set()

    def join(self, timeout=None) -> None:
        self._thread.join(timeout=timeout)


class CompatibilityRuntime:
    def __init__(self, plugin_name: str, *, command_type: type | None = None) -> None:
        self.plugin_name = plugin_name
        self.configuration = MappingProxyType({})
        self.status = SimpleNamespace(state="running", alive=True, thread_id=None)
        self.closed = False
        self.subscriptions: list[CompatibilitySubscription] = []
        self.workers: list[str] = []
        self.advice: list[tuple[str, int]] = []
        self._worker_handles: dict[str, CompatibilityWorker] = {}
        self._command_type = command_type

    def dispatch(self, command):
        future: concurrent.futures.Future = concurrent.futures.Future()
        command_type = self._command_type
        if command_type is None:
            try:
                from zara.runtime.commands import RuntimeCommand
            except ImportError:
                RuntimeCommand = None
            command_type = RuntimeCommand
        if command_type is not None and not isinstance(command, command_type):
            future.set_exception(TypeError("plugins may dispatch RuntimeCommand instances only"))
            return future
        if self.closed:
            future.set_exception(RuntimeError("plugin runtime is closed"))
            return future
        future.set_exception(RuntimeError("compatibility runtime does not execute commands"))
        return future

    def subscribe(self, *, maxsize=None):
        queue_size = 256 if maxsize is None else maxsize
        if not isinstance(queue_size, int) or isinstance(queue_size, bool):
            raise TypeError("event queue size must be an integer")
        if not 1 <= queue_size <= 4096:
            raise ValueError("event queue size must be between 1 and 4096")
        if self.closed:
            raise RuntimeError("plugin runtime is closed")
        self.subscriptions = [
            subscription
            for subscription in self.subscriptions
            if not subscription.closed
        ]
        if len(self.subscriptions) >= 16:
            raise RuntimeError("plugin subscription limit reached")
        subscription = CompatibilitySubscription()
        self.subscriptions.append(subscription)
        return subscription

    def register_agent_loop_advice(self, kind, priority, callback):
        if self.closed:
            raise RuntimeError("plugin runtime is closed")
        if kind not in {"before", "after", "around", "override"}:
            raise ValueError(f"unknown hook kind: {kind!r}")
        if isinstance(priority, bool) or not isinstance(priority, int):
            raise ValueError("priority must be an integer")
        if abs(priority) > 100_000:
            raise ValueError("priority is outside the supported range")
        if not callable(callback):
            raise ValueError("callback must be callable")
        registration_id = len(self.advice) + 1
        self.advice.append((kind, priority))
        return registration_id

    def start_worker(self, name, target):
        if not name or len(name) > 64:
            raise ValueError("worker name must contain 1 to 64 characters")
        if not callable(target):
            raise TypeError("worker target must be callable")
        if inspect.iscoroutinefunction(target):
            raise TypeError("worker target must be synchronous")
        try:
            inspect.signature(target).bind(object())
        except ValueError:
            pass
        except TypeError as error:
            raise TypeError("worker target must accept one stop_event argument") from error
        if self.closed:
            raise RuntimeError("plugin runtime is closed")
        if name in self.workers:
            raise ValueError(f"managed worker {name!r} is already registered")
        if len(self.workers) >= 8:
            raise RuntimeError("managed worker limit reached")
        worker = CompatibilityWorker(f"{self.plugin_name}-{name}", target)
        self.workers.append(name)
        self._worker_handles[name] = worker
        worker.start()
        return worker

    def _shutdown(self) -> None:
        if self.closed:
            return
        self.closed = True
        for subscription in self.subscriptions:
            subscription.close()
        workers = tuple(self._worker_handles.values())
        for worker in workers:
            worker.request_stop()
        deadline = time.monotonic() + 5.0
        for worker in workers:
            worker.join(timeout=max(0.0, deadline - time.monotonic()))
            if worker.is_alive:
                raise RuntimeError(
                    f"managed worker {worker.name!r} did not stop before the deadline"
                )
            if worker.error is not None:
                raise RuntimeError(
                    f"managed worker {worker.name!r} failed: {worker.error}"
                ) from worker.error


def _invoke_lifecycle(method, *args, timeout: float = 5.0) -> None:
    async def invoke() -> None:
        if inspect.iscoroutinefunction(method):
            operation = method(*args)
        else:
            operation = asyncio.to_thread(method, *args)
        await asyncio.wait_for(operation, timeout=timeout)

    asyncio.run(invoke())


def exercise_service_lifecycle(
    instance: object,
    runtime: object,
    *,
    timeout: float = 5.0,
) -> None:
    started = False
    try:
        started = True
        _invoke_lifecycle(instance.start, runtime, timeout=timeout)
    finally:
        try:
            if started:
                _invoke_lifecycle(instance.stop, timeout=timeout)
        finally:
            shutdown = getattr(runtime, "_shutdown", None)
            if callable(shutdown):
                shutdown()
