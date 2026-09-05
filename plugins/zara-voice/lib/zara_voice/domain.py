from __future__ import annotations


class VoiceError(RuntimeError):
    pass


class VoiceDomain:
    def __init__(
        self,
        backends,
        *,
        allow_remote: bool = False,
        max_text_bytes: int = 8192,
        max_duration_ms: int = 5 * 60 * 1000,
    ) -> None:
        if not isinstance(backends, dict) or not backends or len(backends) > 32:
            raise VoiceError("backends must contain between 1 and 32 voice backends")
        if not 1 <= int(max_text_bytes) <= 1_048_576:
            raise VoiceError("max_text_bytes is out of range")
        if not 100 <= int(max_duration_ms) <= 60 * 60 * 1000:
            raise VoiceError("max_duration_ms is out of range")
        self._backends = dict(backends)
        self._allow_remote = bool(allow_remote)
        self._max_text_bytes = int(max_text_bytes)
        self._max_duration_ms = int(max_duration_ms)

    @staticmethod
    def _text(value, name, limit=1024):
        if not isinstance(value, str) or not value.strip():
            raise VoiceError(f"{name} must be a non-empty string")
        if len(value.encode("utf-8")) > limit:
            raise VoiceError(f"{name} exceeds byte limit")
        if any(ord(character) < 0x20 for character in value):
            raise VoiceError(f"{name} contains control characters")
        return value

    def _backend(self, name):
        name = self._text(name, "backend", 128)
        backend = self._backends.get(name)
        if backend is None:
            raise VoiceError("voice backend is unavailable")
        metadata = self._metadata(name, backend)
        if metadata["locality"] == "remote" and not self._allow_remote:
            raise VoiceError("remote voice backend is not allowed without explicit opt-in")
        return name, backend, metadata

    @classmethod
    def _metadata(cls, name, backend):
        raw = backend.describe()
        if not isinstance(raw, dict):
            raise VoiceError("voice backend returned invalid metadata")
        locality = raw.get("locality")
        if locality not in {"local", "remote"}:
            raise VoiceError("voice backend locality must be local or remote")

        def values(field, limit):
            value = raw.get(field, [])
            if not isinstance(value, list) or len(value) > limit:
                raise VoiceError(f"voice backend {field} are invalid")
            return [cls._text(item, field[:-1] if field.endswith("s") else field, 128) for item in value]

        return {
            "backend": name,
            "locality": locality,
            "languages": values("languages", 128),
            "styles": values("styles", 128),
            "emotions": values("emotions", 128),
            "streaming": bool(raw.get("streaming", False)),
        }

    def backends(self):
        return [
            self._metadata(name, self._backends[name])
            for name in sorted(self._backends)
        ]

    def profiles(self, backend):
        name, adapter, metadata = self._backend(backend)
        values = adapter.profiles()
        if not isinstance(values, list) or len(values) > 256:
            raise VoiceError("voice backend returned invalid profiles")
        normalized = []
        for value in values:
            if not isinstance(value, dict):
                raise VoiceError("voice profile is invalid")
            profile_id = self._text(value.get("profile_id"), "profile id", 256)
            profile_name = self._text(value.get("name"), "profile name", 512)
            languages = value.get("languages", [])
            if not isinstance(languages, list) or len(languages) > 128:
                raise VoiceError("voice profile languages are invalid")
            normalized_languages = [self._text(item, "language", 128) for item in languages]
            normalized.append(
                {
                    "backend": name,
                    "profile_id": profile_id,
                    "name": profile_name,
                    "languages": normalized_languages,
                    "locality": metadata["locality"],
                }
            )
        return normalized

    def synthesize(
        self,
        text,
        *,
        backend,
        profile_id,
        language=None,
        style=None,
        emotion=None,
    ):
        text = self._text(text, "text", self._max_text_bytes)
        name, adapter, metadata = self._backend(backend)
        profile_id = self._text(profile_id, "profile id", 256)
        profiles = {profile["profile_id"]: profile for profile in self.profiles(name)}
        profile = profiles.get(profile_id)
        if profile is None:
            raise VoiceError("voice profile is unavailable")

        if language is not None:
            language = self._text(language, "language", 128)
            if language not in profile["languages"] or language not in metadata["languages"]:
                raise VoiceError("language is not supported by voice profile")
        if style is not None:
            style = self._text(style, "style", 128)
            if style not in metadata["styles"]:
                raise VoiceError("style is not supported by voice backend")
        if emotion is not None:
            emotion = self._text(emotion, "emotion", 128)
            if emotion not in metadata["emotions"]:
                raise VoiceError("emotion is not supported by voice backend")

        request = {
            "text": text,
            "profile_id": profile_id,
            "language": language,
            "style": style,
            "emotion": emotion,
        }
        raw = adapter.synthesize(request)
        if not isinstance(raw, dict):
            raise VoiceError("voice backend returned invalid synthesis result")
        artifact_id = self._text(raw.get("artifact_id"), "artifact id", 256)
        output_format = self._text(raw.get("format"), "audio format", 32)
        try:
            sample_rate = int(raw.get("sample_rate_hz"))
            duration_ms = int(raw.get("duration_ms"))
        except (TypeError, ValueError) as error:
            raise VoiceError("voice backend returned invalid audio metadata") from error
        if not 8000 <= sample_rate <= 384000:
            raise VoiceError("sample rate is out of range")
        if not 0 < duration_ms <= self._max_duration_ms:
            raise VoiceError("duration exceeds configured limit")
        if raw.get("backend") != name or raw.get("profile_id") != profile_id:
            raise VoiceError("voice backend returned mismatched artifact identity")
        return {
            "status": "ready",
            "artifact_id": artifact_id,
            "format": output_format,
            "sample_rate_hz": sample_rate,
            "duration_ms": duration_ms,
            "backend": name,
            "profile_id": profile_id,
            "locality": metadata["locality"],
        }

    def play(self, artifact_id, *, backend):
        artifact_id = self._text(artifact_id, "artifact id", 256)
        name, adapter, _ = self._backend(backend)
        evidence = adapter.play(artifact_id)
        accepted = isinstance(evidence, dict) and bool(evidence.get("accepted"))
        playback_id = evidence.get("playback_id") if isinstance(evidence, dict) else None
        state = adapter.playback_state(playback_id) if accepted and playback_id else None
        verified = (
            accepted
            and isinstance(state, dict)
            and state.get("playback_id") == playback_id
            and state.get("state") in {"playing", "streaming"}
        )
        return {
            "status": "verified" if verified else "verification_failed",
            "accepted": accepted,
            "verified": verified,
            "backend": name,
            "playback_id": playback_id,
            "state": state,
            "evidence": evidence,
        }

    def cancel(self, playback_id, *, backend):
        playback_id = self._text(playback_id, "playback id", 256)
        name, adapter, _ = self._backend(backend)
        evidence = adapter.cancel(playback_id)
        accepted = isinstance(evidence, dict) and bool(evidence.get("accepted"))
        state = adapter.playback_state(playback_id) if accepted else None
        verified = (
            accepted
            and isinstance(state, dict)
            and state.get("playback_id") == playback_id
            and state.get("state") in {"cancelled", "stopped"}
        )
        return {
            "status": "verified" if verified else "verification_failed",
            "accepted": accepted,
            "verified": verified,
            "backend": name,
            "playback_id": playback_id,
            "state": state,
            "evidence": evidence,
        }
