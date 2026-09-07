from __future__ import annotations

import secrets
import shutil
import subprocess
import threading
from dataclasses import dataclass
from typing import Any, Callable

from .domain import VoiceError


@dataclass
class _Playback:
    process: Any
    writer: threading.Thread


class PipeWirePlayer:
    """Bounded local WAV playback through PipeWire's pw-play CLI."""

    def __init__(
        self,
        *,
        max_audio_bytes: int = 16 * 1024 * 1024,
        max_active_playbacks: int = 8,
        terminate_timeout: float = 1.0,
        kill_timeout: float = 0.5,
        locator: Callable[[str], str | None] = shutil.which,
        process_factory: Callable[..., Any] = subprocess.Popen,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        if max_audio_bytes <= 0 or max_active_playbacks <= 0:
            raise ValueError("PipeWire player limits must be positive")
        if terminate_timeout <= 0 or kill_timeout <= 0:
            raise ValueError("PipeWire cancellation timeouts must be positive")
        self.max_audio_bytes = max_audio_bytes
        self.max_active_playbacks = max_active_playbacks
        self.terminate_timeout = terminate_timeout
        self.kill_timeout = kill_timeout
        self._locator = locator
        self._process_factory = process_factory
        self._id_factory = id_factory or (lambda: secrets.token_urlsafe(18))
        self._playbacks: dict[str, _Playback] = {}
        self._lock = threading.Lock()

    def play(self, artifact: dict[str, Any]) -> dict[str, Any]:
        audio = artifact.get("audio")
        if not isinstance(audio, bytes) or not audio:
            raise VoiceError("audio player requires non-empty audio bytes")
        if len(audio) > self.max_audio_bytes:
            raise VoiceError("audio exceeds configured player byte limit")
        audio_format = artifact.get("format")
        if not isinstance(audio_format, str) or audio_format.lower() != "wav":
            raise VoiceError("PipeWire player supports wav format only")

        executable = self._locator("pw-play")
        if not executable:
            raise VoiceError("PipeWire audio player unavailable")

        with self._lock:
            self._reap_finished_locked()
            if len(self._playbacks) >= self.max_active_playbacks:
                raise VoiceError("active playback limit reached")

            try:
                process = self._process_factory(
                    [executable, "-"],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    shell=False,
                    close_fds=True,
                )
            except (FileNotFoundError, OSError) as exc:
                raise VoiceError("PipeWire audio player unavailable") from exc

            stdin = getattr(process, "stdin", None)
            if stdin is None:
                self._terminate_untracked(process)
                raise VoiceError("PipeWire audio player did not provide an input stream")

            playback_id = self._new_playback_id_locked()
            writer = threading.Thread(
                target=self._write_audio,
                args=(stdin, audio),
                name=f"zara-voice-pw-play-{playback_id[:8]}",
                daemon=True,
            )
            self._playbacks[playback_id] = _Playback(process=process, writer=writer)
            writer.start()

        return {
            "playback_id": playback_id,
            "state": "process_started",
            "backend": "pipewire-pw-play",
            "audible_confirmed": False,
        }

    def cancel(self, playback_id: str) -> bool:
        if not isinstance(playback_id, str) or not playback_id:
            raise VoiceError("playback id is required")

        with self._lock:
            playback = self._playbacks.get(playback_id)
            if playback is None:
                raise VoiceError("unknown or stale playback id")
            process = playback.process
            if process.poll() is not None:
                self._playbacks.pop(playback_id, None)
                raise VoiceError("unknown or stale playback id")

            process.terminate()
            try:
                process.wait(timeout=self.terminate_timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=self.kill_timeout)
                except subprocess.TimeoutExpired as exc:
                    self._playbacks.pop(playback_id, None)
                    raise VoiceError("playback cancellation exceeded configured time bound") from exc
            finally:
                self._playbacks.pop(playback_id, None)
        return True

    def close(self) -> None:
        with self._lock:
            playback_ids = list(self._playbacks)
        for playback_id in playback_ids:
            try:
                self.cancel(playback_id)
            except VoiceError:
                continue

    def _reap_finished_locked(self) -> None:
        finished = [
            playback_id
            for playback_id, playback in self._playbacks.items()
            if playback.process.poll() is not None
        ]
        for playback_id in finished:
            self._playbacks.pop(playback_id, None)

    def _new_playback_id_locked(self) -> str:
        for _ in range(8):
            playback_id = self._id_factory()
            if isinstance(playback_id, str) and playback_id and playback_id not in self._playbacks:
                return playback_id
        raise VoiceError("unable to allocate unique playback id")

    @staticmethod
    def _write_audio(stdin: Any, audio: bytes) -> None:
        try:
            stdin.write(audio)
            stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass
        finally:
            try:
                stdin.close()
            except (OSError, ValueError):
                pass

    def _terminate_untracked(self, process: Any) -> None:
        try:
            process.terminate()
            process.wait(timeout=self.terminate_timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=self.kill_timeout)
            except subprocess.TimeoutExpired:
                pass
        except OSError:
            pass
