from __future__ import annotations

import concurrent.futures
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
        subscription = CompatibilitySubscription()
        self.subscriptions.append(subscription)
        return subscription

    def register_agent_loop_advice(self, kind, priority, callback):
        registration_id = len(self.advice) + 1
        self.advice.append((str(kind), int(priority)))
        return registration_id

    def start_worker(self, name, target):
        if not callable(target):
            raise TypeError("worker target must be callable")
        self.workers.append(str(name))
        return SimpleNamespace(
            name=str(name),
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


def exercise_service_lifecycle(instance: object, runtime: object) -> None:
    started = False
    try:
        started = True
        instance.start(runtime)
    finally:
        try:
            if started:
                instance.stop()
        finally:
            shutdown = getattr(runtime, "_shutdown", None)
            if callable(shutdown):
                shutdown()
