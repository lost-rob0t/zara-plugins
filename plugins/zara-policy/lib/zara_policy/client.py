"""Bounded data-only transport to an isolated SWI-Prolog policy process."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import shutil
import signal
import subprocess
import threading
import time
from typing import Any

MAX_TEXT_CHARS = 32768
MAX_REQUEST_BYTES = 262144
MAX_RESPONSE_BYTES = 262144
MAX_STDERR_BYTES = 4096
PROLOG_DIR = Path(__file__).resolve().parent / 'prolog'
_PROCESS_SLOTS = threading.BoundedSemaphore(2)


def default_config_path() -> Path:
    root = Path(os.environ.get('XDG_CONFIG_HOME', Path.home() / '.config'))
    return root / 'zarathushtra' / 'plugins' / 'zara-policy' / 'config.pl'


def clean_advice(report: dict[str, Any]) -> list[str]:
    if report.get('status') != 'ok':
        return []
    advice = []
    findings = report.get('findings')
    if not isinstance(findings, list):
        return []
    for finding in findings[:32]:
        if not isinstance(finding, dict):
            continue
        text = finding.get('advice')
        if isinstance(text, str) and 0 < len(text) <= 1024 and text not in advice:
            advice.append(text)
    return advice


def _stop(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    process.wait()


def _exchange(argv: list[str], payload: bytes, timeout: float) -> bytes:
    deadline = time.monotonic() + timeout
    with subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, start_new_session=True, bufsize=0) as process:
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        try:
            with selectors.DefaultSelector() as selector:
                streams = (process.stdin, process.stdout, process.stderr)
                for stream in streams:
                    os.set_blocking(stream.fileno(), False)
                selector.register(process.stdin, selectors.EVENT_WRITE, 'input')
                selector.register(process.stdout, selectors.EVENT_READ, 'output')
                selector.register(process.stderr, selectors.EVENT_READ, 'error')
                sent = 0
                buffers = {'output': bytearray(), 'error': bytearray()}
                limits = {'output': MAX_RESPONSE_BYTES, 'error': MAX_STDERR_BYTES}
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('policy evaluation timed out')
                    for key, _ in selector.select(min(remaining, 0.05)):
                        stream = key.fileobj
                        if key.data == 'input':
                            try:
                                sent += os.write(stream.fileno(), payload[sent:sent + 4096])
                            except BrokenPipeError:
                                sent = len(payload)
                            if sent == len(payload):
                                selector.unregister(stream)
                                stream.close()
                            continue
                        chunk = os.read(stream.fileno(), 8192)
                        if not chunk:
                            selector.unregister(stream)
                            continue
                        buffer = buffers[key.data]
                        if len(buffer) + len(chunk) > limits[key.data]:
                            raise ValueError('policy output limit exceeded')
                        buffer.extend(chunk)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError('policy evaluation timed out')
                if process.wait(timeout=remaining) != 0:
                    raise RuntimeError('policy subprocess failed')
                return bytes(buffers['output'])
        finally:
            _stop(process)


class PolicyClient:
    def __init__(self, *, executable: str | None = None,
                 config_path: Path | None = None, timeout: float = 3.0) -> None:
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0.1 <= timeout <= 10:
            raise ValueError('timeout must be between 0.1 and 10 seconds')
        bundled = PROLOG_DIR / 'swipl'
        self.executable = executable or os.environ.get(
            'ZARA_POLICY_SWIPL', str(bundled) if bundled.is_file() else 'swipl')
        self.config_path = Path(config_path) if config_path is not None else None
        self.timeout = float(timeout)

    def advise(self, text: str) -> dict[str, Any]:
        if not isinstance(text, str):
            raise TypeError('text must be a string')
        if len(text) > MAX_TEXT_CHARS:
            raise ValueError(f'text exceeds {MAX_TEXT_CHARS} characters; split it explicitly')
        return self._request({'op': 'advise', 'text': text, 'context': {}})

    def rules(self, *, offset: int = 0, limit: int = 16) -> dict[str, Any]:
        for name, value, maximum in [('offset', offset, 512), ('limit', limit, 128)]:
            minimum = 1 if name == 'limit' else 0
            if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
                raise ValueError(f'{name} must be an integer between {minimum} and {maximum}')
        return self._request({'op': 'rules', 'offset': offset, 'limit': limit})

    def _request(self, request: dict[str, Any]) -> dict[str, Any]:
        executable = shutil.which(self.executable)
        if executable is None:
            return self._unavailable('missing_swipl')
        try:
            config = self._config()
        except OSError:
            return self._unavailable('invalid_config_file')
        if config is False:
            return self._unavailable('invalid_config_file')
        payload = (json.dumps(request, ensure_ascii=True) + '\n').encode('utf-8')
        if len(payload) > MAX_REQUEST_BYTES:
            raise ValueError('policy request exceeds the byte limit')
        return self._evaluate(executable, config, payload, request['op'])

    def _config(self) -> Path | None | bool:
        config = self.config_path
        if config is None:
            env_path = os.environ.get('ZARA_POLICY_CONFIG')
            config = Path(env_path).expanduser() if env_path else default_config_path()
            if not config.exists() and not env_path:
                config = None
        if config is not None and (not config.is_file() or config.stat().st_size > 131072):
            return False
        return config

    def _evaluate(self, executable: str, config: Path | None, payload: bytes, operation: str) -> dict[str, Any]:
        argv = [executable, '-q', '--no-tty', '--stack-limit=64m', '-f', 'none',
                '-s', str(PROLOG_DIR / 'worker.pl'), '--', str(config) if config is not None else '-']
        if not _PROCESS_SLOTS.acquire(blocking=False):
            return self._unavailable('busy')
        try:
            data = _exchange(argv, payload, self.timeout)
            response = json.loads(data)
            if not isinstance(response, dict) or response.get('status') not in ('ok', 'disabled'):
                return self._unavailable('prolog_rejected_config_or_request')
            if operation == 'advise':
                if not isinstance(response.get('findings'), list) or len(response['findings']) > 32:
                    return self._unavailable('invalid_response')
                if any(not isinstance(row, dict) for row in response['findings']):
                    return self._unavailable('invalid_response')
            elif not isinstance(response.get('rules'), list):
                return self._unavailable('invalid_response')
            return response
        except (TimeoutError, subprocess.TimeoutExpired):
            return self._unavailable('timeout')
        except (OSError, ValueError, RuntimeError):
            return self._unavailable('transport_or_config_error')
        finally:
            _PROCESS_SLOTS.release()

    @staticmethod
    def _unavailable(reason: str) -> dict[str, Any]:
        return {'status': 'unavailable', 'reason': reason, 'verdict': 'not_assessed',
                'advice': 'Policy review did not run successfully. Do not treat this as a clean or verified response.'}
