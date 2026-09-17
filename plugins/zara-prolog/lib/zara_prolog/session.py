from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Callable

MAX_GOAL_CHARS = 8192
MAX_REPLY_CHARS = 262144


class PrologSessionError(RuntimeError):
    pass


def _engine():
    from zara.prolog_engine import PrologEngine
    return PrologEngine()


class PrologSession:
    def __init__(self, config_root: Path, *, engine_factory: Callable = _engine):
        self.config_root = Path(config_root)
        self._engine_factory = engine_factory
        self._engine = None
        self._lock = threading.Lock()

    @property
    def ready(self) -> bool:
        return self._engine is not None

    def start(self) -> None:
        with self._lock:
            if self.ready:
                return
            root = Path(__file__).parent
            self.config_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            user_file = self.config_root / "config.pl"
            try:
                descriptor = os.open(user_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, "w") as output:
                    output.write((root / "config.pl").read_text())
            try:
                engine = self._engine_factory()
                engine.consult(root / "session.pl")
                engine.consult(user_file)
                self._engine = engine
            except Exception:
                raise PrologSessionError("prolog-startup-failed") from None

    def stop(self) -> None:
        with self._lock:
            self._engine = None

    def reload(self) -> dict:
        with self._lock:
            if self._engine is None:
                raise PrologSessionError("prolog-not-started")
            try:
                self._engine.consult(self.config_root / "config.pl")
            except Exception:
                raise PrologSessionError("prolog-reload-failed") from None
            return {"status": "reloaded", "scope": "operator", "transactional": False}

    def query(self, goal: str, max_solutions: int = 16) -> dict:
        if not isinstance(goal, str) or not goal.strip() or len(goal) > MAX_GOAL_CHARS:
            raise PrologSessionError("prolog-goal-invalid")
        if type(max_solutions) is not int or not 1 <= max_solutions <= 64:
            raise PrologSessionError("prolog-solution-limit-invalid")
        request = json.dumps({"goal": goal, "max_solutions": max_solutions}, ensure_ascii=True)
        encoded = json.dumps(request, ensure_ascii=True)
        with self._lock:
            if self._engine is None:
                raise PrologSessionError("prolog-not-started")
            try:
                row = self._engine.query_once(f"zara_prolog_session:query_json({encoded}, Reply)")
                reply = row["Reply"]
                if not isinstance(reply, str) or len(reply) > MAX_REPLY_CHARS:
                    raise ValueError
                value = json.loads(reply)
                if not isinstance(value, dict) or value.get("status") not in {"success", "failure"}:
                    raise ValueError
                if not isinstance(value.get("solutions"), list):
                    raise ValueError
                return value
            except Exception:
                raise PrologSessionError("prolog-query-failed") from None
