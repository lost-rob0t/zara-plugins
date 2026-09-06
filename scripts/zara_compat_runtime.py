from __future__ import annotations

import asyncio
import concurrent.futures
import inspect
import os
import queue
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace


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
    variables = {}
    if plugin_name == "zara-discord":
        variables["ZARA_DISCORD_TOKEN"] = "compatibility-fixture-not-a-secret"

    previous = {name: os.environ.get(name) for name in variables}
    try:
        os.environ.update(variables)
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


class CompatibilityRuntime:
    def __init__(self, plugin_name: str) -> None:
        self.plugin_name = plugin_name
        self.configuration = {}
        self.status = SimpleNamespace(state="running", alive=True, thread_id=None)
        self.closed = False
        self.subscriptions: list[CompatibilitySubscription] = []
        self.workers: list[str] = []
        self.advice: list[tuple[str, int]] = []

    def dispatch(self, command):
        future: concurrent.futures.Future = concurrent.futures.Future()
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
        registration_id = len(self.advice) + 1
        self.advice.append((str(kind), int(priority)))
        return registration_id

    def start_worker(self, name, target):
        if not name or len(name) > 64:
            raise ValueError("worker name must contain 1 to 64 characters")
        if not callable(target):
            raise TypeError("worker target must be callable")
        if self.closed:
            raise RuntimeError("plugin runtime is closed")
        if name in self.workers:
            raise ValueError(f"managed worker {name!r} is already registered")
        if len(self.workers) >= 8:
            raise RuntimeError("managed worker limit reached")
        self.workers.append(name)
        return SimpleNamespace(
            name=name,
            is_alive=False,
            request_stop=lambda: None,
            join=lambda timeout=None: None,
        )

    def _shutdown(self) -> None:
        if self.closed:
            return
        self.closed = True
        for subscription in self.subscriptions:
            subscription.close()


def _invoke_lifecycle(method, *args) -> None:
    async def invoke() -> None:
        if inspect.iscoroutinefunction(method):
            await method(*args)
        else:
            await asyncio.to_thread(method, *args)

    asyncio.run(invoke())


def exercise_service_lifecycle(instance: object, runtime: object) -> None:
    started = False
    try:
        started = True
        _invoke_lifecycle(instance.start, runtime)
    finally:
        try:
            if started:
                _invoke_lifecycle(instance.stop)
        finally:
            shutdown = getattr(runtime, "_shutdown", None)
            if callable(shutdown):
                shutdown()
