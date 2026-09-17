from __future__ import annotations

import asyncio
import json
import os
import threading
from pathlib import Path
from typing import Callable

from .review import PolicyError, mask_prose, parse_report


def _engine():
    from zara.prolog_engine import PrologEngine
    return PrologEngine()


class PolicyBackend:
    def __init__(self, config_root: Path, *, engine_factory: Callable = _engine):
        self.config_root = Path(config_root)
        self._engine_factory = engine_factory
        self._engine = None
        self._lock = threading.Lock()
        self._admission = threading.BoundedSemaphore(1)
        self.mode = 'off'
        self.max_repairs = 1
        self.timeout_seconds = 20
        self.max_text_chars = 65536
        self.profile = 'balanced'
        self.match_count = 0
        self.last_rule_ids: tuple[str, ...] = ()

    @property
    def ready(self) -> bool:
        return self._engine is not None

    def start(self) -> None:
        with self._lock:
            if self.ready:
                return
            root = Path(__file__).parent
            self.config_root.mkdir(parents=True, exist_ok=True, mode=0o700)
            config = self.config_root / 'config.pl'
            try:
                descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                with os.fdopen(descriptor, 'w') as output:
                    output.write((root / 'config.pl').read_text())
            try:
                engine = self._engine_factory()
                engine.consult(root / 'engine.pl')
                engine.consult(config)
                row = engine.query_once('zara_policy:settings_json(Reply)')
                settings = json.loads(row['Reply'])
                self._configure(settings)
                self._engine = engine
            except Exception:
                self.mode = 'off'
                raise PolicyError('policy-startup-failed') from None

    def _configure(self, settings: dict) -> None:
        if settings.get('mode') not in ('off', 'observe', 'advise'):
            raise PolicyError('policy-mode-invalid')
        if settings.get('profile') not in ('balanced', 'direct'):
            raise PolicyError('policy-profile-invalid')
        for key, low, high in (('max_repairs', 0, 1), ('timeout_seconds', 1, 60),
                               ('max_text_chars', 1, 65536)):
            value = settings.get(key)
            if type(value) is not int or not low <= value <= high:
                raise PolicyError('policy-setting-invalid')
        for key in ('mode', 'profile', 'max_repairs', 'timeout_seconds', 'max_text_chars'):
            setattr(self, key, settings[key])

    def stop(self) -> None:
        with self._lock:
            self._engine = None
            self.mode = 'off'
            self.last_rule_ids = ()

    def inspect(self, text: str):
        if not isinstance(text, str) or len(text) > self.max_text_chars:
            raise PolicyError('policy-text-invalid')
        request = json.dumps({'text': mask_prose(text)}, ensure_ascii=True)
        encoded = json.dumps(request, ensure_ascii=True)
        with self._lock:
            if self._engine is None:
                raise PolicyError('policy-not-started')
            try:
                row = self._engine.query_once(f'zara_policy:inspect_json({encoded}, Reply)')
                findings = parse_report(row['Reply'])
            except Exception:
                raise PolicyError('policy-evaluation-failed') from None
            self.match_count += len(findings)
            self.last_rule_ids = tuple(item.rule_id for item in findings)
            return findings

    async def inspect_async(self, text: str):
        if not self._admission.acquire(blocking=False):
            raise PolicyError('policy-busy')
        def run():
            try:
                return self.inspect(text)
            finally:
                self._admission.release()
        loop = asyncio.get_running_loop()
        try:
            future = loop.run_in_executor(None, run)
        except BaseException:
            self._admission.release()
            raise
        return await asyncio.wait_for(asyncio.shield(future), timeout=2.0)
