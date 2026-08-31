"""Deterministic stub renderer speaking the zara-avatar stdio protocol.

Used only by tests. Behaviors:

- prints a ``ready`` event on startup
- echoes a successful response for every known command
- ``FailRequest`` responds with an error using ``message``
- ``HangRequest`` never responds
- ``Crash`` exits immediately with status 2
- ``LoadAvatar`` emits an ``avatarLoaded`` event

Set ``STUB_RENDERER_STARTUP_DELAY`` (seconds) to delay readiness.
Set ``STUB_LOAD_DELAY`` (seconds) to delay each LoadAvatar response.
"""

from __future__ import annotations

import json
import os
import sys
import time


def emit(document: dict) -> None:
    sys.stdout.write(json.dumps(document, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def main() -> None:
    delay = float(os.environ.get("STUB_RENDERER_STARTUP_DELAY", "0"))
    if delay:
        time.sleep(delay)
    emit({"event": "ready", "params": {"stub": True}})
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        command = request.get("command")
        request_id = request.get("id")
        if command == "Shutdown":
            sys.stdout.flush()
            return
        if command == "Crash":
            sys.stdout.flush()
            os._exit(2)
        if command == "HangRequest":
            continue
        if command == "FailRequest":
            emit(
                {
                    "id": request_id,
                    "ok": False,
                    "error": request.get("params", {}).get("message", "failed"),
                }
            )
            continue
        if command == "LoadAvatar":
            load_delay = float(os.environ.get("STUB_LOAD_DELAY", "0"))
            if load_delay:
                time.sleep(load_delay)
            emit({"event": "avatarLoaded", "params": {"avatarId": request["params"].get("avatarId")}})
        emit(
            {
                "id": request_id,
                "ok": True,
                "result": {"command": command},
            }
        )


if __name__ == "__main__":
    main()
