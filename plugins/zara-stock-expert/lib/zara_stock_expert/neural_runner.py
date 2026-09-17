from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from .domain import bounded_int
from .neural import MAX_BYTES, canonical


class NeuralRunner:
    """One isolated CPU worker at a time; no pickle, remote code or model downloads."""

    def __init__(self, timeout_seconds: int = 60) -> None:
        self.timeout = bounded_int(timeout_seconds, 5, 120)
        self._gate = threading.Lock()
        self._state = threading.Lock()
        self._process = None
        self._stopped = False

    def run(self, operation: str, arguments: dict) -> dict:
        if operation not in ('train', 'forecast'):
            raise ValueError('unknown neural operation')
        payload = canonical(dict(operation=operation, arguments=arguments)).encode('utf-8')
        if len(payload) > 2 * MAX_BYTES:
            raise ValueError('neural input exceeds bound')
        if not self._gate.acquire(blocking=False):
            raise RuntimeError('neural worker is busy; no unbounded training queue')
        process = None
        try:
            environment = {key: os.environ[key] for key in
                ('PATH', 'SystemRoot', 'WINDIR', 'TMP', 'TEMP', 'LD_LIBRARY_PATH') if key in os.environ}
            environment.update(OMP_NUM_THREADS='1', MKL_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1',
                CUDA_VISIBLE_DEVICES='-1', HIP_VISIBLE_DEVICES='-1', HF_HUB_OFFLINE='1', PYTHONNOUSERSITE='1')
            with self._state:
                if self._stopped:
                    raise RuntimeError('neural worker is stopped')
                process = subprocess.Popen([sys.executable, '-I', str(Path(__file__).with_name('neural_worker.py'))],
                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    env=environment, shell=False, close_fds=True)
                self._process = process
            try:
                output, _ = process.communicate(input=payload, timeout=self.timeout)
            except subprocess.TimeoutExpired as error:
                self._kill(process)
                process.communicate(timeout=5)
                raise TimeoutError('neural deadline exceeded; worker killed and no result persisted') from error
            if process.returncode != 0 or len(output) > MAX_BYTES:
                raise RuntimeError('neural worker failed or exceeded output bound')
            try:
                result = json.loads(output)
                if not isinstance(result, dict):
                    raise ValueError('invalid result')
                if result.get('ok') is not True:
                    code = result.get('error')
                    if code not in ('optional_pytorch_dependency_missing', 'invalid_neural_data_or_artifact',
                                    'neural_computation_failed', 'output_bound_exceeded'):
                        code = 'worker_failure'
                    raise RuntimeError('neural worker: ' + code)
                if not isinstance(result.get('value'), dict):
                    raise ValueError('invalid value')
                return result['value']
            except (ValueError, UnicodeError) as error:
                raise RuntimeError('invalid neural worker protocol') from error
        finally:
            with self._state:
                self._process = None
            if process is not None and process.poll() is None:
                self._kill(process)
                process.wait(timeout=5)
            self._gate.release()

    @staticmethod
    def _kill(process) -> None:
        try:
            process.kill()
        except ProcessLookupError:
            pass

    def stop(self) -> None:
        with self._state:
            self._stopped = True
            process = self._process
            if process is not None and process.poll() is None:
                self._kill(process)
        if process is not None:
            process.wait(timeout=5)
