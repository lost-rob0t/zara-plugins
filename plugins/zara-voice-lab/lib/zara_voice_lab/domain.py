from __future__ import annotations

import hashlib
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


class VoiceLabError(RuntimeError):
    pass


@dataclass(frozen=True)
class VoiceLabPolicy:
    max_sample_bytes: int = 32 * 1024 * 1024
    max_dataset_bytes: int = 256 * 1024 * 1024
    max_preview_bytes: int = 16 * 1024 * 1024
    allow_remote: bool = False

    def __post_init__(self) -> None:
        if min(self.max_sample_bytes, self.max_dataset_bytes, self.max_preview_bytes) <= 0:
            raise ValueError("voice-lab limits must be positive")


class VoiceLabService:
    def __init__(
        self,
        *,
        backends: Mapping[str, Any],
        workspace_root: Path,
        policy: VoiceLabPolicy | None = None,
    ) -> None:
        self.backends = dict(backends)
        self.workspace_root = Path(workspace_root)
        self.policy = policy or VoiceLabPolicy()
        self._profiles: dict[str, dict[str, Any]] = {}

    def create_profile(
        self,
        *,
        name: str,
        backend: str,
        samples: list[dict[str, Any]],
        mode: str,
        source_provenance: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip() or len(name) > 64:
            raise VoiceLabError("profile name must contain 1 to 64 characters")
        selected = self.backends.get(backend)
        if selected is None:
            raise VoiceLabError(f"voice-lab backend not found: {backend}")
        locality = str(getattr(selected, "locality", ""))
        if locality not in {"local", "remote"}:
            raise VoiceLabError("voice-lab backend locality must be explicit")
        if locality == "remote" and not self.policy.allow_remote:
            raise VoiceLabError("remote voice processing is disabled by policy")
        capabilities = frozenset(str(item) for item in getattr(selected, "capabilities", ()))
        if mode not in {"clone", "create"} or mode not in capabilities:
            raise VoiceLabError(f"backend does not support requested mode: {mode}")
        if not isinstance(source_provenance, dict) or not source_provenance:
            raise VoiceLabError("source provenance is required")
        normalized = self._validate_samples(samples)

        temporary_root = self.workspace_root / "tmp"
        temporary_root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix="voice-lab-", dir=temporary_root))
        try:
            staged = []
            for sample in normalized:
                path = temporary / sample["name"]
                path.write_bytes(sample["audio"])
                staged.append({key: value for key, value in sample.items() if key != "audio"} | {"path": str(path)})
            result = selected.create(
                {
                    "name": name.strip(),
                    "mode": mode,
                    "samples": staged,
                    "source_provenance": dict(source_provenance),
                }
            )
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

        if not isinstance(result, dict):
            raise VoiceLabError("voice-lab backend returned invalid profile data")
        backend_profile = result.get("backend_profile")
        model = result.get("model")
        config = result.get("config")
        if not isinstance(backend_profile, str) or not backend_profile:
            raise VoiceLabError("voice-lab backend did not identify runtime profile")
        if not isinstance(model, str) or not model or not isinstance(config, dict):
            raise VoiceLabError("voice-lab backend did not provide model/config provenance")

        profile_id = self._profile_id(name.strip(), backend, backend_profile)
        record = {
            "profile_id": profile_id,
            "name": name.strip(),
            "backend": backend,
            "backend_profile": backend_profile,
            "locality": locality,
            "model": model,
            "config": dict(config),
            "source_provenance": dict(source_provenance),
            "mode": mode,
        }
        self._profiles[profile_id] = record
        return dict(record)

    def preview(self, profile_id: str, text: str, *, style: str | None = None) -> dict[str, Any]:
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise VoiceLabError(f"voice profile not found: {profile_id}")
        backend = self.backends[profile["backend"]]
        capabilities = frozenset(str(item) for item in getattr(backend, "capabilities", ()))
        if style is not None and "style" not in capabilities:
            raise VoiceLabError("voice-lab backend does not support style")
        if not isinstance(text, str) or not text.strip():
            raise VoiceLabError("preview text is required")
        result = backend.preview({"backend_profile": profile["backend_profile"], "text": text, "style": style})
        if not isinstance(result, dict) or not isinstance(result.get("audio"), bytes):
            raise VoiceLabError("voice-lab backend returned invalid preview audio")
        if len(result["audio"]) > self.policy.max_preview_bytes:
            raise VoiceLabError("preview audio exceeds configured limit")
        duration = result.get("duration_seconds")
        audio_format = result.get("format")
        if not isinstance(duration, (int, float)) or isinstance(duration, bool) or duration < 0:
            raise VoiceLabError("voice-lab backend returned invalid preview duration")
        if not isinstance(audio_format, str) or not audio_format:
            raise VoiceLabError("voice-lab backend returned invalid preview format")
        return {
            "profile_id": profile_id,
            "profile_name": profile["name"],
            "backend": profile["backend"],
            "backend_profile": profile["backend_profile"],
            "format": audio_format,
            "duration_seconds": float(duration),
            "bytes": len(result["audio"]),
        }

    def export_profile(self, profile_id: str) -> dict[str, Any]:
        profile = self._profiles.get(profile_id)
        if profile is None:
            raise VoiceLabError(f"voice profile not found: {profile_id}")
        return {
            "runtime_schema": "zara-voice-profile-v1",
            "name": profile["name"],
            "backend": profile["backend"],
            "backend_profile": profile["backend_profile"],
            "locality": profile["locality"],
            "model": profile["model"],
            "config": dict(profile["config"]),
            "source_provenance": dict(profile["source_provenance"]),
        }

    def _validate_samples(self, samples: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not isinstance(samples, list) or not samples:
            raise VoiceLabError("at least one source sample is required")
        normalized = []
        total = 0
        for sample in samples:
            if not isinstance(sample, dict):
                raise VoiceLabError("source sample must be structured data")
            name = sample.get("name")
            audio = sample.get("audio")
            audio_format = sample.get("format")
            sample_rate = sample.get("sample_rate_hz")
            if not isinstance(name, str) or not name or Path(name).name != name:
                raise VoiceLabError("source sample name must be a safe basename")
            if not isinstance(audio, bytes) or not audio:
                raise VoiceLabError("source sample must contain audio bytes")
            if len(audio) > self.policy.max_sample_bytes:
                raise VoiceLabError("source sample exceeds configured sample limit")
            total += len(audio)
            if total > self.policy.max_dataset_bytes:
                raise VoiceLabError("source dataset exceeds configured dataset limit")
            if not isinstance(audio_format, str) or not audio_format:
                raise VoiceLabError("source sample format is required")
            if not isinstance(sample_rate, int) or isinstance(sample_rate, bool) or sample_rate <= 0:
                raise VoiceLabError("source sample rate must be positive")
            normalized.append({"name": name, "audio": audio, "format": audio_format, "sample_rate_hz": sample_rate})
        return normalized

    @staticmethod
    def _profile_id(name: str, backend: str, backend_profile: str) -> str:
        digest = hashlib.sha256(f"{name}\0{backend}\0{backend_profile}".encode()).hexdigest()
        return digest[:24]
