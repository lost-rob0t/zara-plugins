"""Shared support for Zara avatar plugin tests.

Loads ``zara-plugin/zara_avatar.py`` against a fake ``zara.plugins`` API so
tests never require Zarathushtra to be installed.
"""

from __future__ import annotations

import dataclasses
import importlib.util
import sys
import threading
import types
from concurrent.futures import Future
from pathlib import Path
from queue import Empty, Queue


@dataclasses.dataclass(frozen=True)
class _PluginMetadata:
    name: str
    version: str = ""
    api_version: str = "1"
    plugin_type: str = "service"
    description: str = ""


class _ServicePlugin:
    pass


@dataclasses.dataclass(frozen=True, kw_only=True)
class _RuntimeEvent:
    label: str = ""
    turn_id: str | None = None


@dataclasses.dataclass(frozen=True, kw_only=True)
class _RuntimeStatus:
    state: str = "running"
    alive: bool = True
    thread_id: int = 123


@dataclasses.dataclass(frozen=True)
class _Envelope:
    sequence: int
    occurred_at: float
    event: object


class _Subscription:
    def __init__(self, maxsize: int) -> None:
        self.queue: Queue = Queue(maxsize=maxsize)
        self.closed = False
        self.dropped_count = 0

    def get(self, timeout=None):
        if self.closed:
            raise Empty()
        return self.queue.get(timeout=timeout)

    def get_nowait(self):
        return self.queue.get_nowait()

    def drain(self, limit=None):
        items = []
        while True:
            try:
                items.append(self.queue.get_nowait())
            except Empty:
                break
            if limit is not None and len(items) >= limit:
                break
        return items

    def close(self) -> None:
        self.closed = True

    def publish(self, event) -> None:
        if self.closed:
            return
        self.queue.put(
            _Envelope(sequence=0, occurred_at=0.0, event=event), timeout=1
        )


class _Worker:
    def __init__(self, name, target) -> None:
        self.name = name
        self.stop_event = threading.Event()
        self.thread = threading.Thread(
            name=f"test-{name}",
            target=target,
            args=(self.stop_event,),
            daemon=True,
        )
        self.thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self.stop_event.set()
        self.thread.join(timeout=timeout)


class _FakeRuntime:
    """Minimal PluginRuntime stand-in for the avatar plugin."""

    def __init__(self, configuration=None) -> None:
        self.configuration = configuration or {}
        self.status = _RuntimeStatus()
        self.subscription = _Subscription(maxsize=256)
        self.workers: list[tuple[str, _Worker]] = []
        self.worker_names: list[str] = []
        self.failures: list[str] = []
        self.closed = False

    def subscribe(self, *, maxsize: int):
        return self.subscription

    def start_worker(self, name, target):
        self.worker_names.append(name)
        worker = _Worker(name, target)
        self.workers.append((name, worker))
        return worker

    def report_failure(self, message: str) -> None:
        self.failures.append(message)

    def dispatch(self, command):
        future: Future = Future()
        future.set_exception(NotImplementedError("runtime dispatch not used"))
        return future

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.subscription.close()
        for _, worker in self.workers:
            worker.stop()


def load_avatar_module():
    """Import zara_avatar.py with the Zara plugin API stubbed."""
    zara = types.ModuleType("zara")
    plugins = types.ModuleType("zara.plugins")
    plugins.PluginMetadata = _PluginMetadata
    plugins.ServicePlugin = _ServicePlugin
    zara.plugins = plugins
    modules = {"zara": zara, "zara.plugins": plugins}
    previous = {name: sys.modules.get(name) for name in modules}
    sys.modules.update(modules)
    try:
        path = (
            Path(__file__).parents[1] / "zara-plugin" / "zara_avatar.py"
        ).resolve()
        spec = importlib.util.spec_from_file_location(
            "zara_avatar_under_test", path
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for name, value in previous.items():
            if value is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = value
