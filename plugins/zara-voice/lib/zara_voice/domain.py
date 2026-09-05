from __future__ import annotations

import hashlib
import os
from pathlib import Path


class VoiceError(RuntimeError):
    pass


class VoiceDomain:
    def __init__(
        self,
        backends,
        cache_root,
        *,
        max_text_bytes=16_384,
        max_audio_bytes=32 * 1024 * 1024,
        max_duration_seconds=600,
        max_cache_bytes=256 * 1024 * 1024,
    ):
        if not isinstance(backends, dict) or not backends or len(backends) > 64:
            raise VoiceError("backends must contain between 1 and 64 configured TTS backends")
        if not 1 <= int(max_text_bytes) <= 1_048_576:
            raise VoiceError("max_text_bytes is out of range")
        if not 1 <= int(max_audio_bytes) <= 1_073_741_824:
            raise VoiceError("max_audio_bytes is out of range")
        if not 1 <= int(max_duration_seconds) <= 86_400:
            raise VoiceError("max_duration_seconds is out of range")
        if not 1 <= int(max_cache_bytes) <= 10_737_418_240:
            raise VoiceError("max_cache_bytes is out of range")
        self.backends = dict(backends)
        self.cache_root = Path(cache_root).expanduser()
        self.max_text_bytes = int(max_text_bytes)
        self.max_audio_bytes = int(max_audio_bytes)
        self.max_duration_seconds = float(max_duration_seconds)
        self.max_cache_bytes = int(max_cache_bytes)
        self._artifacts = {}
        self._cache_order = []
        self._playbacks = {}

    @staticmethod
    def _text(value, name, max_bytes=1024, *, allow_empty=False):
        if not isinstance(value, str) or (not allow_empty and not value.strip()):
            raise VoiceError(f"{name} must be a string")
        if len(value.encode("utf-8")) > max_bytes:
            raise VoiceError(f"{name} exceeds byte limit")
        if any(ord(ch) < 0x20 and ch not in "\n\r\t" for ch in value):
            raise VoiceError(f"{name} contains invalid control characters")
        return value

    def _backend(self, name):
        name = self._text(name, "backend", 128)
        backend = self.backends.get(name)
        if backend is None:
            raise VoiceError("backend is unavailable")
        locality = getattr(backend, "locality", None)
        if locality not in {"local", "remote"}:
            raise VoiceError("backend locality must be local or remote")
        capabilities = getattr(backend, "capabilities", set())
        if not isinstance(capabilities, (set, frozenset, list, tuple)):
            raise VoiceError("backend capabilities are invalid")
        return name, backend, locality, set(capabilities)

    def profiles(self):
        results = []
        for name in sorted(self.backends):
            _, backend, locality, capabilities = self._backend(name)
            raw_profiles = backend.profiles()
            if not isinstance(raw_profiles, list) or len(raw_profiles) > 512:
                raise VoiceError("backend returned invalid profiles")
            for raw in raw_profiles:
                if not isinstance(raw, dict):
                    raise VoiceError("profile is invalid")
                profile_id = self._text(raw.get("profile_id"), "profile id", 256)
                profile_name = self._text(raw.get("name"), "profile name", 512)
                languages = raw.get("languages", [])
                styles = raw.get("styles", [])
                emotions = raw.get("emotions", [])
                if not all(isinstance(values, list) and len(values) <= 128 for values in (languages, styles, emotions)):
                    raise VoiceError("profile capabilities are invalid")
                results.append({
                    "backend": name,
                    "locality": locality,
                    "capabilities": sorted(capabilities),
                    "profile_id": profile_id,
                    "name": profile_name,
                    "languages": [self._text(value, "language", 64) for value in languages],
                    "styles": [self._text(value, "style", 128) for value in styles],
                    "emotions": [self._text(value, "emotion", 128) for value in emotions],
                })
        return results

    def _profile(self, backend_name, profile_id):
        matches = [item for item in self.profiles() if item["backend"] == backend_name and item["profile_id"] == profile_id]
        if len(matches) != 1:
            raise VoiceError("profile is unavailable or ambiguous")
        return matches[0]

    def _evict(self):
        total = sum(Path(meta["path"]).stat().st_size for meta in self._artifacts.values() if Path(meta["path"]).exists())
        while total > self.max_cache_bytes and self._cache_order:
            artifact_id = self._cache_order.pop(0)
            meta = self._artifacts.pop(artifact_id, None)
            if meta is None:
                continue
            path = Path(meta["path"])
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                size = 0
            try:
                path.unlink()
            except FileNotFoundError:
                pass
            total -= size

    def synthesize(
        self,
        text,
        *,
        backend,
        profile_id,
        language=None,
        style=None,
        emotion=None,
        allow_remote=False,
    ):
        text = self._text(text, "text", self.max_text_bytes)
        backend_name, adapter, locality, capabilities = self._backend(backend)
        profile_id = self._text(profile_id, "profile id", 256)
        profile = self._profile(backend_name, profile_id)
        if locality == "remote" and not allow_remote:
            raise VoiceError("remote synthesis requires explicit allow_remote")
        if language is not None:
            language = self._text(language, "language", 64)
            if profile["languages"] and language not in profile["languages"]:
                raise VoiceError("language is unsupported by profile")
        if style is not None:
            style = self._text(style, "style", 128)
            if "style" not in capabilities or style not in profile["styles"]:
                raise VoiceError("style is unsupported by backend/profile")
        if emotion is not None:
            emotion = self._text(emotion, "emotion", 128)
            if "emotion" not in capabilities or emotion not in profile["emotions"]:
                raise VoiceError("emotion is unsupported by backend/profile")
        request = {
            "text": text,
            "profile_id": profile_id,
            "language": language,
            "style": style,
            "emotion": emotion,
        }
        raw = adapter.synthesize(request)
        if not isinstance(raw, dict):
            raise VoiceError("backend returned invalid synthesis result")
        audio = raw.get("audio")
        if not isinstance(audio, (bytes, bytearray)):
            raise VoiceError("backend audio is invalid")
        audio = bytes(audio)
        if len(audio) > self.max_audio_bytes:
            raise VoiceError("audio exceeds byte limit")
        format_name = self._text(raw.get("format"), "audio format", 32)
        if not format_name.replace("-", "").replace("_", "").isalnum():
            raise VoiceError("audio format is invalid")
        sample_rate = int(raw.get("sample_rate"))
        if not 1 <= sample_rate <= 384_000:
            raise VoiceError("sample rate is out of range")
        duration = float(raw.get("duration_seconds"))
        if not 0 <= duration <= self.max_duration_seconds:
            raise VoiceError("duration exceeds configured limit")
        digest = hashlib.sha256()
        for value in (backend_name, profile_id, text, language or "", style or "", emotion or ""):
            digest.update(value.encode("utf-8"))
            digest.update(b"\0")
        digest.update(audio)
        artifact_id = f"voice-{digest.hexdigest()[:24]}"
        self.cache_root.mkdir(parents=True, exist_ok=True)
        path = (self.cache_root / f"{artifact_id}.{format_name}").resolve()
        root = self.cache_root.resolve()
        if not path.is_relative_to(root):
            raise VoiceError("cache path escaped configured root")
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(audio)
                handle.flush()
                os.fsync(handle.fileno())
        except Exception:
            try:
                os.close(fd)
            except OSError:
                pass
            raise
        artifact = {
            "artifact_id": artifact_id,
            "backend": backend_name,
            "locality": locality,
            "profile_id": profile_id,
            "language": language,
            "style": style,
            "emotion": emotion,
            "format": format_name,
            "sample_rate": sample_rate,
            "duration_seconds": duration,
            "bytes": len(audio),
            "path": str(path),
        }
        if artifact_id in self._cache_order:
            self._cache_order.remove(artifact_id)
        self._cache_order.append(artifact_id)
        self._artifacts[artifact_id] = artifact
        self._evict()
        if artifact_id not in self._artifacts:
            raise VoiceError("audio exceeds configured cache budget")
        return dict(artifact)

    def play(self, artifact_id):
        artifact_id = self._text(artifact_id, "artifact id", 128)
        artifact = self._artifacts.get(artifact_id)
        if artifact is None or not Path(artifact["path"]).is_file():
            raise VoiceError("artifact is unavailable")
        backend_name, adapter, _, _ = self._backend(artifact["backend"])
        evidence = adapter.play(dict(artifact))
        accepted = isinstance(evidence, dict) and bool(evidence.get("accepted"))
        playback_id = evidence.get("playback_id") if accepted else None
        if accepted:
            playback_id = self._text(playback_id, "playback id", 256)
            self._playbacks[playback_id] = backend_name
        return {"accepted": accepted, "backend": backend_name, "playback_id": playback_id, "evidence": evidence}

    def cancel(self, playback_id):
        playback_id = self._text(playback_id, "playback id", 256)
        backend_name = self._playbacks.get(playback_id)
        if backend_name is None:
            raise VoiceError("playback is unavailable")
        _, adapter, _, _ = self._backend(backend_name)
        evidence = adapter.cancel(playback_id)
        accepted = isinstance(evidence, dict) and bool(evidence.get("accepted"))
        if accepted:
            self._playbacks.pop(playback_id, None)
        return {"accepted": accepted, "backend": backend_name, "playback_id": playback_id, "evidence": evidence}

    def health(self):
        result = {}
        for name in sorted(self.backends):
            _, adapter, locality, _ = self._backend(name)
            try:
                raw = adapter.health()
                if not isinstance(raw, dict):
                    raise VoiceError("invalid health result")
                status = raw.get("status")
                if status not in {"ready", "degraded", "unavailable", "unknown"}:
                    raise VoiceError("invalid health status")
                result[name] = {"status": status, "locality": locality, "latency_ms": raw.get("latency_ms")}
            except Exception as error:
                result[name] = {"status": "unknown", "locality": locality, "error_type": type(error).__name__}
        return result
