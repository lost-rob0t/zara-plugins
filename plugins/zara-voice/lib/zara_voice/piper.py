from __future__ import annotations

import importlib
import io
import uuid
import wave
from pathlib import Path
from typing import Any, Callable

from .domain import VoiceError


class _BoundedBytesIO(io.BytesIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self._limit = limit

    def write(self, data: bytes) -> int:
        end = self.tell() + len(data)
        if end > self._limit:
            raise VoiceError("Piper audio exceeds configured output limit")
        return super().write(data)


class PiperBackend:
    name = "piper-local"
    locality = "local"
    capabilities = frozenset()

    def __init__(
        self,
        *,
        model_path: Path | str,
        config_path: Path | str,
        max_audio_bytes: int = 16 * 1024 * 1024,
        use_cuda: bool = False,
        loader: Callable[..., Any] | None = None,
        import_module: Callable[[str], Any] = importlib.import_module,
    ) -> None:
        self._model_path = Path(model_path)
        self._config_path = Path(config_path)
        self._max_audio_bytes = int(max_audio_bytes)
        self._use_cuda = bool(use_cuda)
        self._loader = loader
        self._import_module = import_module
        self._voice: Any | None = None

        if self._max_audio_bytes <= 0:
            raise ValueError("Piper output limit must be positive")
        if not self._model_path.is_file():
            raise VoiceError("Piper voice model is unavailable")
        if not self._config_path.is_file():
            raise VoiceError("Piper voice config is unavailable")

    def synthesize(self, request: Any) -> dict[str, Any]:
        if not isinstance(request, dict):
            raise VoiceError("Piper synthesis request is invalid")
        text = request.get("text")
        if not isinstance(text, str) or not text.strip():
            raise VoiceError("Piper synthesis request is invalid")

        voice = self._get_voice()
        output = _BoundedBytesIO(self._max_audio_bytes)
        try:
            with wave.open(output, "wb") as wav_file:
                voice.synthesize_wav(text, wav_file)
            audio = output.getvalue()
        except VoiceError:
            raise
        except Exception:
            raise VoiceError("Piper synthesis failed") from None

        sample_rate, duration = self._wav_metadata(audio)
        return {
            "audio": audio,
            "format": "wav",
            "sample_rate_hz": sample_rate,
            "duration_seconds": duration,
            "request_id": uuid.uuid4().hex,
        }

    def _get_voice(self) -> Any:
        if self._voice is not None:
            return self._voice

        loader = self._loader
        if loader is None:
            try:
                module = self._import_module("piper")
                loader = module.PiperVoice.load
            except Exception:
                raise VoiceError("Piper backend is unavailable") from None

        try:
            voice = loader(
                self._model_path,
                config_path=self._config_path,
                use_cuda=self._use_cuda,
            )
        except Exception:
            raise VoiceError("Piper voice failed to load") from None
        if voice is None or not callable(getattr(voice, "synthesize_wav", None)):
            raise VoiceError("Piper voice failed to load")

        self._voice = voice
        return voice

    @staticmethod
    def _wav_metadata(audio: bytes) -> tuple[int, float]:
        try:
            with wave.open(io.BytesIO(audio), "rb") as wav_file:
                sample_rate = wav_file.getframerate()
                frames = wav_file.getnframes()
                channels = wav_file.getnchannels()
                sample_width = wav_file.getsampwidth()
        except (EOFError, wave.Error):
            raise VoiceError("Piper returned invalid WAV audio") from None

        if sample_rate <= 0 or frames <= 0 or channels <= 0 or sample_width <= 0:
            raise VoiceError("Piper returned invalid WAV audio")
        return sample_rate, frames / sample_rate
