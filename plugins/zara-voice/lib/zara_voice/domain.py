from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class VoiceError(RuntimeError):
    pass


@dataclass(frozen=True)
class VoicePolicy:
    max_text_chars: int = 4000
    max_audio_bytes: int = 16 * 1024 * 1024
    max_duration_seconds: float = 120.0
    max_cache_bytes: int = 128 * 1024 * 1024
    allow_remote: bool = False

    def __post_init__(self) -> None:
        if min(self.max_text_chars, self.max_audio_bytes, self.max_cache_bytes) <= 0:
            raise ValueError("voice byte/text limits must be positive")
        if self.max_duration_seconds <= 0:
            raise ValueError("voice duration limit must be positive")


@dataclass(frozen=True)
class VoiceProfile:
    name: str
    backend: str
    backend_profile: str
    language: str | None = None

    def __post_init__(self) -> None:
        if not self.name or len(self.name) > 64:
            raise ValueError("voice profile name must contain 1 to 64 characters")
        if not self.backend or not self.backend_profile:
            raise ValueError("voice profile must identify backend and backend profile")


class VoiceService:
    def __init__(
        self,
        *,
        backends: Mapping[str, Any],
        player: Any,
        cache_root: Path,
        policy: VoicePolicy | None = None,
    ) -> None:
        self.backends = dict(backends)
        self.player = player
        self.cache_root = Path(cache_root)
        self.policy = policy or VoicePolicy()
        self._profiles: dict[str, VoiceProfile] = {}
        self._artifacts: dict[str, dict[str, Any]] = {}
        self._request_backends: dict[str, Any] = {}

    def register_profile(self, profile: VoiceProfile) -> None:
        if profile.name in self._profiles:
            raise VoiceError(f"voice profile already registered: {profile.name}")
        if profile.backend not in self.backends:
            raise VoiceError(f"voice backend is not registered: {profile.backend}")
        self._profiles[profile.name] = profile

    def profiles(self) -> list[dict[str, Any]]:
        result = []
        for profile in sorted(self._profiles.values(), key=lambda value: value.name):
            backend = self.backends[profile.backend]
            result.append(
                {
                    "name": profile.name,
                    "backend": profile.backend,
                    "backend_profile": profile.backend_profile,
                    "language": profile.language,
                    "locality": self._locality(backend),
                    "capabilities": sorted(self._capabilities(backend)),
                }
            )
        return result

    def synthesize(
        self,
        text: str,
        *,
        profile: str,
        language: str | None = None,
        style: str | None = None,
        emotion: str | None = None,
        cache: bool = True,
    ) -> dict[str, Any]:
        if not isinstance(text, str) or not text.strip() or len(text) > self.policy.max_text_chars:
            raise VoiceError("text is empty or exceeds configured text limit")
        selected = self._profiles.get(profile)
        if selected is None:
            raise VoiceError(f"voice profile not found: {profile}")
        backend = self.backends[selected.backend]
        locality = self._locality(backend)
        if locality == "remote" and not self.policy.allow_remote:
            raise VoiceError("remote TTS backend is disabled by policy")
        if locality not in {"local", "remote"}:
            raise VoiceError("voice backend locality must be explicit")

        capabilities = self._capabilities(backend)
        if language is not None and "language" not in capabilities:
            raise VoiceError("voice backend does not support language selection")
        if style is not None and "style" not in capabilities:
            raise VoiceError("voice backend does not support style")
        if emotion is not None and "emotion" not in capabilities:
            raise VoiceError("voice backend does not support emotion")

        request = {
            "text": text,
            "profile": selected.backend_profile,
            "language": language or selected.language,
            "style": style,
            "emotion": emotion,
        }
        result = backend.synthesize(request)
        artifact = self._validate_backend_result(result, selected, locality)
        artifact_id = self._artifact_id(artifact, text)
        artifact["artifact_id"] = artifact_id
        self._artifacts[artifact_id] = dict(artifact)
        request_id = artifact.get("request_id")
        if isinstance(request_id, str) and request_id:
            self._request_backends[request_id] = backend
        if cache:
            self._cache(artifact_id, artifact["audio"])
        return self._public_artifact(artifact)

    def play(self, artifact_id: str) -> dict[str, Any]:
        artifact = self._artifacts.get(artifact_id)
        if artifact is None:
            raise VoiceError(f"voice artifact not found: {artifact_id}")
        result = self.player.play(dict(artifact))
        if not isinstance(result, dict) or not isinstance(result.get("playback_id"), str):
            raise VoiceError("audio player returned invalid playback evidence")
        return dict(result)

    def cancel(self, *, playback_id: str | None = None, request_id: str | None = None) -> dict[str, Any]:
        if bool(playback_id) == bool(request_id):
            raise VoiceError("provide exactly one playback_id or request_id")
        if playback_id:
            cancelled = self.player.cancel(playback_id)
            return {"kind": "playback", "id": playback_id, "cancelled": bool(cancelled)}
        assert request_id is not None
        backend = self._request_backends.get(request_id)
        if backend is None:
            return {"kind": "synthesis", "id": request_id, "cancelled": False}
        callback = getattr(backend, "cancel", None)
        if callback is None:
            return {"kind": "synthesis", "id": request_id, "cancelled": False}
        return {"kind": "synthesis", "id": request_id, "cancelled": bool(callback(request_id))}

    def _validate_backend_result(self, result: Any, profile: VoiceProfile, locality: str) -> dict[str, Any]:
        if not isinstance(result, dict):
            raise VoiceError("voice backend returned invalid synthesis data")
        audio = result.get("audio")
        if not isinstance(audio, bytes):
            raise VoiceError("voice backend did not return audio bytes")
        if len(audio) > self.policy.max_audio_bytes:
            raise VoiceError("audio exceeds configured output limit")
        duration = result.get("duration_seconds")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
            raise VoiceError("voice backend returned invalid duration")
        if duration > self.policy.max_duration_seconds:
            raise VoiceError("audio exceeds configured duration limit")
        sample_rate = result.get("sample_rate_hz")
        if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate <= 0:
            raise VoiceError("voice backend returned invalid sample rate")
        audio_format = result.get("format")
        if not isinstance(audio_format, str) or not audio_format:
            raise VoiceError("voice backend returned invalid audio format")
        request_id = result.get("request_id")
        if request_id is not None and (not isinstance(request_id, str) or not request_id):
            raise VoiceError("voice backend returned invalid request id")
        return {
            "audio": audio,
            "format": audio_format,
            "sample_rate_hz": sample_rate,
            "duration_seconds": float(duration),
            "request_id": request_id,
            "backend": profile.backend,
            "profile": profile.name,
            "backend_profile": profile.backend_profile,
            "locality": locality,
        }

    def _cache(self, artifact_id: str, audio: bytes) -> None:
        self.cache_root.mkdir(parents=True, exist_ok=True)
        path = self.cache_root / f"{artifact_id}.audio"
        temporary = self.cache_root / f".{artifact_id}.{os.getpid()}.tmp"
        temporary.write_bytes(audio)
        os.replace(temporary, path)
        self._evict_cache()

    def _evict_cache(self) -> None:
        paths = sorted(
            self.cache_root.glob("*.audio"),
            key=lambda path: (path.stat().st_mtime_ns, path.name),
        )
        total = sum(path.stat().st_size for path in paths)
        for path in paths:
            if total <= self.policy.max_cache_bytes:
                break
            size = path.stat().st_size
            path.unlink(missing_ok=True)
            total -= size

    @staticmethod
    def _artifact_id(artifact: dict[str, Any], text: str) -> str:
        digest = hashlib.sha256()
        digest.update(artifact["backend"].encode())
        digest.update(b"\0")
        digest.update(artifact["backend_profile"].encode())
        digest.update(b"\0")
        digest.update(text.encode())
        digest.update(b"\0")
        digest.update(artifact["audio"])
        return digest.hexdigest()[:24]

    @staticmethod
    def _public_artifact(artifact: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in artifact.items() if key != "audio"}

    @staticmethod
    def _locality(backend: Any) -> str:
        return str(getattr(backend, "locality", ""))

    @staticmethod
    def _capabilities(backend: Any) -> frozenset[str]:
        capabilities = getattr(backend, "capabilities", frozenset())
        return frozenset(str(value) for value in capabilities)
