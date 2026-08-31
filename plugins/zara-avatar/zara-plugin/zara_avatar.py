"""Zara-owned 3D avatar presentation plugin for Zara's service-plugin API.

zara-avatar is an optional presentation plugin. Zara's brain, memory, and
relationship state live elsewhere; this plugin owns only presentation: the
selected avatar, its visible state, expression, animation, gaze, speech
visuals, and the renderer child process.

Authoritative avatar state is owned by a single serialized AvatarActor. HTTP
handlers, event subscriptions, and callbacks send commands to the actor and
never mutate state directly.
"""

from __future__ import annotations

import base64
import binascii
import concurrent.futures
import dataclasses
import hashlib
import ipaddress
import json
import math
import os
import queue
import re
import shutil
import stat
import struct
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping, Optional

from zara.plugins import PluginMetadata, ServicePlugin

ZARA_AVATAR = True
AVATAR_PLUGIN_VERSION = "0.1.0"
AVATAR_API_VERSION = "1"

PRESENCES = ("idle", "listening", "thinking", "speaking")
EMOTIONS = ("neutral", "happy", "sad", "annoyed", "excited", "embarrassed")
EXPRESSIONS = (
    "neutral",
    "happy",
    "sad",
    "angry",
    "annoyed",
    "relaxed",
    "surprised",
    "excited",
    "embarrassed",
)
GESTURES = ("wave", "nod", "shrug", "point")
FRAMINGS = ("half", "full")
SEMANTIC_ANIMATIONS = (
    "idle",
    "thinking",
    "wave",
    "nod",
    "shrug",
    "point",
    "happy",
    "sad",
    "annoyed",
    "excited",
)
VISEMES = ("a", "i", "u", "e", "o")

MAX_SPEED = 4.0
MIN_SPEED = 0.1
MAX_DURATION = 60.0
MIN_DURATION = 0.1
MAX_SCALE = 5.0
MIN_SCALE = 0.1
MAX_AXIS = 10.0
MAX_ROTATION = 360.0
MAX_NAME = 64
MAX_SAMPLE_RATE = 192000


class AvatarProtocolError(Exception):
    """A malformed avatar protocol operation."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


# Emotion -> semantic expression. Zara owns semantic state; the avatar plugin
# maps it onto presentation.
EMOTION_EXPRESSIONS = {
    "neutral": "neutral",
    "happy": "happy",
    "sad": "sad",
    "annoyed": "annoyed",
    "excited": "excited",
    "embarrassed": "embarrassed",
}

# Ordered fallback chains. The last entry is always "neutral"; a VRM that
# lacks a requested expression degrades gracefully instead of crashing.
EXPRESSION_FALLBACKS = {
    "neutral": ("neutral",),
    "happy": ("happy", "relaxed", "neutral"),
    "sad": ("sad", "neutral"),
    "angry": ("angry", "annoyed", "neutral"),
    "annoyed": ("annoyed", "angry", "neutral"),
    "relaxed": ("relaxed", "happy", "neutral"),
    "surprised": ("surprised", "happy", "neutral"),
    "excited": ("excited", "happy", "neutral"),
    "embarrassed": ("embarrassed", "happy", "neutral"),
}


def expression_for_emotion(emotion: str) -> str:
    """Map a Zara semantic emotion onto a semantic expression."""
    return EMOTION_EXPRESSIONS.get(emotion, "neutral")


def resolve_expression(requested: str, available) -> str:
    """Resolve a semantic expression against an avatar's capabilities.

    ``available`` is the set of semantic expression names the loaded VRM can
    render. Missing morph targets never crash the plugin: the fallback chain
    always ends at ``neutral``.
    """
    chain = EXPRESSION_FALLBACKS.get(requested)
    if chain is None:
        return "neutral"
    for candidate in chain:
        if candidate in available:
            return candidate
    return "neutral"


# ---------------------------------------------------------------------------
# Animation subsystem
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class RendererPlayAnimation:
    clip: str
    loop: bool
    speed: float
    duration: Optional[float]
    crossfade: float


# Only these clips may ever be chosen automatically while the avatar idles.
SAFE_IDLE_CLIPS = ("idle", "thinking")

GESTURE_ANIMATIONS = {
    "wave": "wave",
    "nod": "nod",
    "shrug": "shrug",
    "point": "point",
}

CLIP_DURATIONS = {
    "idle": 8.0,
    "thinking": 6.0,
    "wave": 1.8,
    "nod": 1.2,
    "shrug": 1.5,
    "point": 1.6,
    "happy": 2.5,
    "sad": 3.0,
    "annoyed": 2.5,
    "excited": 2.5,
}

DEFAULT_CROSSFADE = 1.0
MAX_PENDING_ANIMATIONS = 8


class AnimationController:
    """Semantic animation playback state.

    The controller owns playback semantics only: which semantic clip plays,
    loop/speed/duration parameters, the bounded pending queue, and safe
    non-repeating idle scheduling. It never sees file names; the renderer maps
    semantic names onto its local animation manifest.
    """

    def __init__(
        self,
        *,
        crossfade: float = DEFAULT_CROSSFADE,
        seed: int = 0,
        durations: Optional[Mapping[str, float]] = None,
    ) -> None:
        self.crossfade = crossfade
        self._rng = _DeterministicRandom(seed)
        self._durations = dict(CLIP_DURATIONS if durations is None else durations)
        self._current: Optional[str] = None
        self._current_loop = False
        self.pending: list[RendererPlayAnimation] = []
        self._idle_bag: list[str] = []

    @property
    def current(self) -> Optional[str]:
        return self._current

    def reset(self) -> None:
        self._current = None
        self._current_loop = False
        self.pending.clear()

    def next_idle(self) -> str:
        """Draw the next safe idle clip from a seeded, non-repeating bag."""
        if not self._idle_bag:
            self._idle_bag = list(SAFE_IDLE_CLIPS)
            self._rng.shuffle(self._idle_bag)
        return self._idle_bag.pop()

    def play(
        self,
        clip: str,
        *,
        loop: bool = False,
        speed: float = 1.0,
        duration: Optional[float] = None,
    ) -> list:
        """Play a semantic clip, queueing behind the current one if active."""
        if clip not in SEMANTIC_ANIMATIONS:
            raise ValueError(f"unknown semantic animation {clip!r}")
        if not MIN_SPEED <= speed <= MAX_SPEED:
            raise ValueError("speed out of range")
        if duration is not None and not MIN_DURATION <= duration <= MAX_DURATION:
            raise ValueError("duration out of range")
        if duration is None and not loop:
            duration = self._durations[clip]
        command = RendererPlayAnimation(
            clip=clip,
            loop=loop,
            speed=speed,
            duration=duration,
            crossfade=self.crossfade,
        )
        queueing = (
            self._current is not None
            and not self._current_loop
            and self._current not in SAFE_IDLE_CLIPS
        )
        if queueing:
            if len(self.pending) >= MAX_PENDING_ANIMATIONS:
                self.pending.pop(0)
            self.pending.append(command)
            return []
        self._current = clip
        self._current_loop = loop
        return [command]

    def stop(self) -> list:
        """Stop playback immediately and return to a safe idle clip."""
        self.pending.clear()
        return self._play_idle()

    def gesture(self, gesture: str) -> list:
        if gesture not in GESTURE_ANIMATIONS:
            raise ValueError(f"unknown gesture {gesture!r}")
        return self.play(GESTURE_ANIMATIONS[gesture])

    def finish(self) -> list:
        """Advance past a completed non-looping clip (queue or idle)."""
        if self._current is None or self._current_loop:
            return []
        if self.pending:
            command = self.pending.pop(0)
            self._current = command.clip
            self._current_loop = command.loop
            return [command]
        return self._play_idle()

    def _play_idle(self) -> list:
        clip = self.next_idle()
        duration = self._durations[clip]
        command = RendererPlayAnimation(
            clip=clip,
            loop=False,
            speed=1.0,
            duration=duration,
            crossfade=self.crossfade,
        )
        self._current = clip
        self._current_loop = False
        return [command]


class _DeterministicRandom:
    """Small seeded shuffle source so idle scheduling stays testable."""

    def __init__(self, seed: int) -> None:
        self._state = (seed * 6364136223846793005 + 1442695040888963407) % (1 << 64)

    def next_u64(self) -> int:
        self._state = (
            self._state * 6364136223846793005 + 1442695040888963407
        ) % (1 << 64)
        return self._state

    def shuffle(self, items: list) -> None:
        for index in range(len(items) - 1, 0, -1):
            swap = self.next_u64() % (index + 1)
            items[index], items[swap] = items[swap], items[index]


# ---------------------------------------------------------------------------
# Audio-driven lip sync
# ---------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class VisemeFrame:
    """One analyzer output: A/I/U/E/O weights plus raw features."""

    visemes: Mapping[str, float]
    amplitude: float
    frequency: float

    def to_document(self) -> dict[str, float]:
        return {
            name: round(self.visemes[name], 4) for name in VISEMES
        }


LIPSYNC_MODES = ("analyzed", "direct", "hybrid")

# Approximate vowel band centers in Hz (log-frequency membership). Real
# formants differ per model; these are smooth, deterministic heuristics good
# enough for lively mouth motion, and they are independent of sample rate.
_VISEME_BANDS = (
    ("u", 380.0, 0.35),
    ("o", 520.0, 0.40),
    ("a", 750.0, 0.45),
    ("e", 1750.0, 0.50),
    ("i", 2600.0, 0.55),
)

SILENCE_AMPLITUDE = 0.02


class VisemeAnalyzer:
    """Estimate A/I/U/E/O viseme weights from the audio actually playing.

    Provider-neutral: the caller pushes PCM16 little-endian mono chunks from
    any TTS or playback source. Modes:

    - ``analyzed``: visemes estimated from amplitude and zero-crossing rate.
    - ``direct``: caller-provided viseme weights are used literally.
    - ``hybrid``: estimated and provided weights are blended.

    Smoothing (EMA), mouth gain, and volume influence shape the output.
    Silence always closes the mouth and clears smoothing history so speech
    end/cancel can never leave a frozen open mouth.
    """

    def __init__(
        self,
        *,
        sample_rate: int = 16000,
        smoothing: float = 0.35,
        gain: float = 1.0,
        volume_influence: float = 1.0,
        mode: str = "analyzed",
    ) -> None:
        if mode not in LIPSYNC_MODES:
            raise ValueError(f"unknown lip sync mode {mode!r}")
        if not 0.0 <= smoothing <= 1.0:
            raise ValueError("smoothing must be between 0 and 1")
        if gain < 0.0 or gain > 10.0:
            raise ValueError("gain must be between 0 and 10")
        if not 0.0 <= volume_influence <= 2.0:
            raise ValueError("volume_influence must be between 0 and 2")
        self.sample_rate = sample_rate
        self.smoothing = smoothing
        self.gain = gain
        self.volume_influence = volume_influence
        self.mode = mode
        self._history: dict[str, float] = {name: 0.0 for name in VISEMES}

    def reset(self) -> None:
        """Clear smoothing history; the mouth returns to closed."""
        for name in self._history:
            self._history[name] = 0.0

    def process(
        self,
        pcm: bytes,
        *,
        sample_rate: Optional[int] = None,
        visemes: Optional[Mapping[str, float]] = None,
    ) -> VisemeFrame:
        """Analyze one PCM chunk and return the next viseme frame."""
        rate = sample_rate or self.sample_rate
        amplitude, frequency = _pcm_features(pcm, rate)
        if amplitude < SILENCE_AMPLITUDE:
            self.reset()
            return VisemeFrame(
                visemes={name: 0.0 for name in VISEMES},
                amplitude=amplitude,
                frequency=frequency,
            )
        energy = min(1.0, amplitude * self.gain)
        volume_factor = energy**self.volume_influence
        if self.mode == "direct":
            target = _provided_weights(visemes)
        else:
            estimated = _estimated_weights(frequency)
            if self.mode == "hybrid":
                provided = _provided_weights(visemes)
                target = {
                    name: 0.5 * estimated[name] + 0.5 * provided[name]
                    for name in VISEMES
                }
            else:
                target = estimated
            target = {
                name: min(1.0, target[name] * volume_factor) for name in VISEMES
            }
        alpha = 1.0 - self.smoothing
        weights = {}
        for name in VISEMES:
            previous = self._history[name]
            blended = alpha * target[name] + (1.0 - alpha) * previous
            self._history[name] = blended
            weights[name] = blended
        return VisemeFrame(
            visemes=weights,
            amplitude=amplitude,
            frequency=frequency,
        )


def _pcm_features(pcm: bytes, sample_rate: int) -> tuple[float, float]:
    """Return (amplitude 0..1, dominant frequency estimate in Hz)."""
    if not pcm:
        return 0.0, 0.0
    usable = pcm[: len(pcm) - (len(pcm) % 2)]
    count = len(usable) // 2
    if count == 0:
        return 0.0, 0.0
    squares = 0.0
    crossings = 0
    previous = 0
    for index in range(count):
        sample = int.from_bytes(
            usable[index * 2 : index * 2 + 2], "little", signed=True
        )
        normalized = sample / 32768.0
        squares += normalized * normalized
        if index > 0 and (sample >= 0) != (previous >= 0):
            crossings += 1
        previous = sample
    amplitude = math.sqrt(squares / count)
    duration = count / float(sample_rate)
    frequency = (crossings / 2.0) / duration if duration > 0 else 0.0
    return amplitude, frequency


def _estimated_weights(frequency: float) -> dict[str, float]:
    weights = {}
    for name, center, width in _VISEME_BANDS:
        if frequency <= 1.0:
            weights[name] = 0.0
            continue
        distance = math.log(frequency / center) / width
        weights[name] = math.exp(-0.5 * distance * distance)
    return weights


def _provided_weights(visemes: Optional[Mapping[str, float]]) -> dict[str, float]:
    weights = {name: 0.0 for name in VISEMES}
    if not visemes:
        return weights
    for name, value in visemes.items():
        if name in weights and isinstance(value, (int, float)):
            weights[name] = max(0.0, min(1.0, float(value)))
    return weights


# ---------------------------------------------------------------------------
# VRM validation and avatar library
# ---------------------------------------------------------------------------


class InvalidVrmError(Exception):
    """A VRM file was rejected; the message carries a useful diagnostic."""


@dataclasses.dataclass(frozen=True)
class VrmInfo:
    vrm_version: str
    extensions_used: tuple[str, ...]
    title: Optional[str]


@dataclasses.dataclass(frozen=True)
class AvatarRecord:
    avatar_id: str
    name: str
    path: Path
    size_bytes: int
    sha256: str
    vrm_version: str
    imported_at: float

    def to_document(self) -> dict[str, Any]:
        return {
            "avatarId": self.avatar_id,
            "name": self.name,
            "sizeBytes": self.size_bytes,
            "sha256": self.sha256,
            "vrmVersion": self.vrm_version,
            "importedAt": self.imported_at,
        }


def validate_vrm(data: bytes) -> VrmInfo:
    """Validate a VRM (glTF-binary) payload before it is stored or rendered.

    Raises :class:`InvalidVrmError` with a bounded diagnostic for anything
    that is not a plausible VRM 0.x/1.0 model. A corrupt file must never
    reach the renderer or crash the plugin.
    """
    if not data:
        raise InvalidVrmError("empty file: not a VRM model")
    if len(data) < 20:
        raise InvalidVrmError("file too small to be a VRM model")
    magic = data[:4]
    if magic != b"glTF":
        raise InvalidVrmError("missing glTF magic: not a VRM model")
    version, total_length = struct.unpack_from("<II", data, 4)
    if version != 2:
        raise InvalidVrmError(f"unsupported glTF version {version}")
    if total_length < 20 or total_length > len(data):
        raise InvalidVrmError("declared glTF length exceeds available bytes")
    chunk_length, chunk_type = struct.unpack_from("<I4s", data, 12)
    if chunk_type != b"JSON":
        raise InvalidVrmError("first chunk is not JSON")
    if 20 + chunk_length > len(data):
        raise InvalidVrmError("JSON chunk is truncated")
    raw_json = data[20 : 20 + chunk_length]
    try:
        document = json.loads(raw_json.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise InvalidVrmError(f"invalid JSON chunk: {error}") from error
    if not isinstance(document, dict):
        raise InvalidVrmError("JSON chunk must be an object")
    extensions_used = document.get("extensionsUsed")
    if not isinstance(extensions_used, list):
        extensions_used = []
    extensions_used = [
        str(name) for name in extensions_used if isinstance(name, str)
    ]
    if not any(name.startswith("VRM") for name in extensions_used):
        raise InvalidVrmError(
            "glTF payload declares no VRM extension; refusing plain glTF files"
        )
    vrm_version = "0.x"
    title = None
    extensions = document.get("extensions")
    if isinstance(extensions, dict):
        cvrm = extensions.get("VRMCvrm")
        if isinstance(cvrm, dict):
            spec = cvrm.get("specVersion")
            if isinstance(spec, str) and spec.startswith("1"):
                vrm_version = "1.0"
        vrm0 = extensions.get("VRM")
        if isinstance(vrm0, dict):
            meta = vrm0.get("meta")
            if isinstance(meta, dict) and isinstance(meta.get("title"), str):
                title = meta["title"]
    return VrmInfo(
        vrm_version=vrm_version,
        extensions_used=tuple(extensions_used),
        title=title,
    )


def _slugify(name: str) -> str:
    slug = []
    for character in name.strip().lower():
        if character in "abcdefghijklmnopqrstuvwxyz0123456789":
            slug.append(character)
        elif slug and slug[-1] != "-":
            slug.append("-")
    text = "".join(slug).strip("-")
    return text or "avatar"


class AvatarLibrary:
    """Zara-owned storage for imported .vrm avatars."""

    def __init__(self, directory: Path, *, max_bytes: int = 512 * 1024 * 1024) -> None:
        self.directory = Path(directory)
        self.max_bytes = int(max_bytes)
        self.directory.mkdir(parents=True, exist_ok=True)

    def import_avatar(self, name: str, data: bytes) -> AvatarRecord:
        if len(data) > self.max_bytes:
            raise InvalidVrmError(
                f"avatar file exceeds configured limit of {self.max_bytes} bytes"
            )
        info = validate_vrm(data)
        avatar_id = f"{_slugify(name)}-{hashlib.sha256(data).hexdigest()[:8]}"
        path = self._path_for(avatar_id)
        path.write_bytes(data)
        record = AvatarRecord(
            avatar_id=avatar_id,
            name=name,
            path=path,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            vrm_version=info.vrm_version,
            imported_at=time.time(),
        )
        self._write_record(record)
        return record

    def import_from_path(self, name: str, source: Path) -> AvatarRecord:
        source = Path(source)
        if not source.is_file():
            raise FileNotFoundError(f"no such avatar file: {source}")
        size = source.stat().st_size
        if size > self.max_bytes:
            raise InvalidVrmError(
                f"avatar file exceeds configured limit of {self.max_bytes} bytes"
            )
        return self.import_avatar(name, source.read_bytes())

    def list_avatars(self) -> tuple[AvatarRecord, ...]:
        records = []
        for record_path in sorted(self.directory.glob("*.json")):
            try:
                document = json.loads(record_path.read_text(encoding="utf-8"))
                record = self._record_from_document(document)
            except (OSError, ValueError, KeyError):
                continue
            if record is not None:
                records.append(record)
        return tuple(records)

    def get(self, avatar_id: str) -> Optional[AvatarRecord]:
        self._require_safe_id(avatar_id)
        record_path = self.directory / f"{avatar_id}.json"
        if not record_path.is_file():
            return None
        try:
            document = json.loads(record_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        try:
            return self._record_from_document(document)
        except (KeyError, ValueError):
            return None

    def delete(self, avatar_id: str) -> None:
        record = self.get(avatar_id)
        if record is None:
            raise KeyError(avatar_id)
        record.path.unlink(missing_ok=True)
        (self.directory / f"{avatar_id}.json").unlink(missing_ok=True)

    def mark_selected(self, avatar_id: str) -> None:
        self._require_safe_id(avatar_id)
        if self.get(avatar_id) is None:
            raise KeyError(avatar_id)
        (self.directory / "selected.json").write_text(
            json.dumps({"avatarId": avatar_id}), encoding="utf-8"
        )

    def selected(self) -> Optional[str]:
        path = self.directory / "selected.json"
        if not path.is_file():
            return None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            avatar_id = document["avatarId"]
        except (OSError, ValueError, KeyError):
            return None
        if self.get(avatar_id) is None:
            return None
        return avatar_id

    def _path_for(self, avatar_id: str) -> Path:
        return self.directory / f"{avatar_id}.vrm"

    @staticmethod
    def _require_safe_id(avatar_id: str) -> None:
        if not avatar_id or any(
            character not in _AVATAR_ID_CHARACTERS for character in avatar_id
        ):
            raise KeyError(avatar_id)

    def _write_record(self, record: AvatarRecord) -> None:
        document = {
            "avatarId": record.avatar_id,
            "name": record.name,
            "fileName": record.path.name,
            "sizeBytes": record.size_bytes,
            "sha256": record.sha256,
            "vrmVersion": record.vrm_version,
            "importedAt": record.imported_at,
        }
        (self.directory / f"{record.avatar_id}.json").write_text(
            json.dumps(document), encoding="utf-8"
        )

    def _record_from_document(self, document: dict) -> Optional[AvatarRecord]:
        file_name = document["fileName"]
        if "/" in file_name or "\\" in file_name or file_name.startswith("."):
            raise ValueError("unsafe file name")
        path = self.directory / file_name
        if not path.is_file():
            return None
        return AvatarRecord(
            avatar_id=document["avatarId"],
            name=document["name"],
            path=path,
            size_bytes=int(document["sizeBytes"]),
            sha256=str(document["sha256"]),
            vrm_version=str(document["vrmVersion"]),
            imported_at=float(document["importedAt"]),
        )


# ---------------------------------------------------------------------------
# Renderer process boundary
# ---------------------------------------------------------------------------

# The narrow command set the renderer understands. Three.js objects, browser
# internals, and file contents never cross this boundary; only these typed
# commands and JSON events do.
RENDERER_COMMANDS = frozenset(
    {
        "LoadAvatar",
        "UnloadAvatar",
        "SetExpression",
        "SetTransform",
        "SetCamera",
        "SetGaze",
        "SetVisemes",
        "SetLighting",
        "PlayAnimation",
        "StopAnimation",
        "ShowWindow",
        "HideWindow",
        "Shutdown",
    }
)

MAX_RENDERER_PAYLOAD = 512 * 1024


class RendererUnavailable(Exception):
    """The renderer process could not be started or readied."""


class RendererRequestError(Exception):
    """A renderer request failed, timed out, or was answered with an error."""


class RendererHost:
    """Owns the renderer child process over a newline-delimited JSON stdio.

    The host is deliberately narrow: start, request, restart, events, and a
    deterministic shutdown that leaves no orphan processes. It never
    interprets avatar semantics; the AvatarActor does that.
    """

    def __init__(
        self,
        *,
        command: list,
        startup_timeout: float = 10.0,
        request_timeout: float = 5.0,
        shutdown_grace: float = 3.0,
        environment: Optional[Mapping[str, str]] = None,
        allowed_commands: Optional[frozenset] = None,
    ) -> None:
        if not command or not all(isinstance(part, str) for part in command):
            raise ValueError("renderer command must be a list of strings")
        self.command = list(command)
        self.startup_timeout = startup_timeout
        self.request_timeout = request_timeout
        self.shutdown_grace = shutdown_grace
        self.environment = dict(environment) if environment else None
        self.allowed_commands = allowed_commands or RENDERER_COMMANDS
        self.process = None
        self._next_request_id = 1
        self._pending: dict[int, queue.Queue] = {}
        self._events: queue.Queue = queue.Queue(maxsize=256)
        self._reader = None
        self._lock = threading.RLock()
        self._stopped = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        with self._lock:
            if self.process is not None:
                raise RuntimeError("renderer process already started")
            if self._stopped:
                raise RuntimeError("renderer host is stopped")
            try:
                self.process = subprocess.Popen(
                    self.command,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    env=self.environment,
                    close_fds=True,
                )
            except OSError as error:
                raise RendererUnavailable(
                    f"could not spawn renderer: {error}"
                ) from error
            self._reader = threading.Thread(
                name="zara-avatar-renderer-reader",
                target=self._read_loop,
                daemon=True,
            )
            self._reader.start()
        try:
            self._wait_for_event("ready", self.startup_timeout)
        except Exception:
            self.shutdown()
            raise

    @property
    def is_running(self) -> bool:
        process = self.process
        return process is not None and process.poll() is None

    def restart(self) -> None:
        self.shutdown()
        self._stopped = False
        self.start()

    def shutdown(self) -> None:
        """Terminate the renderer deterministically; leave no orphan process."""
        with self._lock:
            if self._stopped and self.process is None:
                return
            self._stopped = True
            process = self.process
            self.process = None
        if process is None:
            return
        if process.poll() is None:
            try:
                self._write_line({"id": 0, "command": "Shutdown", "params": {}})
            except (OSError, ValueError):
                pass
            if process.stdin is not None:
                try:
                    process.stdin.close()
                except OSError:
                    pass
            try:
                process.wait(timeout=self.shutdown_grace)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=self.shutdown_grace)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=self.shutdown_grace)
        if self._reader is not None:
            self._reader.join(timeout=1.0)
            self._reader = None
        for pending in self._pending.values():
            pending.put(None)
        self._pending.clear()

    # -- requests and events -----------------------------------------------

    def request(
        self,
        command: str,
        params: Optional[Mapping[str, Any]] = None,
        *,
        timeout: Optional[float] = None,
    ) -> dict:
        if command not in self.allowed_commands:
            raise ValueError(f"unknown renderer command {command!r}")
        payload = dict(params or {})
        encoded = json.dumps(payload, separators=(",", ":"))
        if len(encoded) > MAX_RENDERER_PAYLOAD:
            raise ValueError("renderer request payload exceeds limit")
        with self._lock:
            if self.process is None or self._stopped:
                raise RendererRequestError("renderer is not running")
            request_id = self._next_request_id
            self._next_request_id += 1
            replies: queue.Queue = queue.Queue(maxsize=1)
            self._pending[request_id] = replies
        try:
            self._write_line({"id": request_id, "command": command, "params": payload})
        except (OSError, ValueError) as error:
            self._pending.pop(request_id, None)
            raise RendererRequestError(f"renderer pipe is broken: {error}") from error
        wait = self.request_timeout if timeout is None else timeout
        try:
            reply = replies.get(timeout=wait)
        except queue.Empty:
            reply = None
        finally:
            self._pending.pop(request_id, None)
        if reply is None:
            if not self.is_running:
                raise RendererRequestError(
                    f"renderer exited while handling {command!r}"
                )
            raise RendererRequestError(
                f"renderer request {command!r} timed out after {wait}s"
            )
        if not reply.get("ok"):
            raise RendererRequestError(
                str(reply.get("error", "renderer request failed"))
            )
        result = reply.get("result")
        return result if isinstance(result, dict) else {}

    def drain_events(self, limit: int = 64) -> list:
        events = []
        while len(events) < limit:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def next_event(self, timeout: Optional[float] = None):
        try:
            return self._events.get(timeout=timeout)
        except queue.Empty:
            return None

    # -- internals ----------------------------------------------------------

    def _write_line(self, document: dict) -> None:
        process = self.process
        if process is None or process.stdin is None:
            raise OSError("renderer stdin is closed")
        line = json.dumps(document, separators=(",", ":"))
        if len(line) > MAX_RENDERER_PAYLOAD:
            raise ValueError("renderer request exceeds line limit")
        process.stdin.write((line + "\n").encode("utf-8"))
        process.stdin.flush()

    def _wait_for_event(self, name: str, timeout: float) -> dict:
        deadline = time.monotonic() + timeout
        buffered = []
        while time.monotonic() < deadline:
            try:
                event = self._events.get(timeout=max(0.0, deadline - time.monotonic()))
            except queue.Empty:
                break
            if event["event"] == name:
                for previous in buffered:
                    self._events.put(previous)
                return event
            buffered.append(event)
        for previous in buffered:
            self._events.put(previous)
        if self.process is not None and self.process.poll() is not None:
            raise RendererUnavailable(
                f"renderer exited during startup with code {self.process.poll()}"
            )
        raise RendererUnavailable(
            f"renderer did not signal {name!r} within {timeout}s"
        )

    def _read_loop(self) -> None:
        process = self.process
        if process is None or process.stdout is None:
            return
        try:
            for line in process.stdout:
                line = line.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    document = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(document, dict):
                    continue
                if "id" in document and ("ok" in document or "error" in document):
                    waiter = self._pending.get(document["id"])
                    if waiter is not None:
                        waiter.put(document)
                    continue
                name = document.get("event")
                if isinstance(name, str):
                    params = document.get("params")
                    self._events.put(
                        {
                            "event": name,
                            "params": params if isinstance(params, dict) else {},
                        }
                    )
        except (OSError, ValueError):
            pass
        finally:
            code = process.poll()
            self._events.put(
                {
                    "event": "rendererExited",
                    "params": {"code": code},
                }
            )
            with self._lock:
                pending = list(self._pending.values())
            for waiter in pending:
                waiter.put(None)


def base64_encode(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def base64_decode(value: str) -> bytes:
    try:
        return base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as error:
        raise AvatarProtocolError("field must be valid base64") from error


@dataclasses.dataclass(frozen=True)
class AvatarState:
    """Typed snapshot of authoritative avatar presentation state."""

    loaded: bool = False
    visible: bool = False
    avatar_id: Optional[str] = None
    presence: str = "idle"
    emotion: str = "neutral"
    expression: str = "neutral"
    animation: Optional[str] = None
    animation_loop: bool = False
    animation_speed: float = 1.0
    gaze_target: str = "auto"
    speaking: bool = False
    lipsync_active: bool = False
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    rotation: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: float = 1.0
    framing: str = "half"

    def to_document(self) -> dict[str, Any]:
        return {
            "loaded": self.loaded,
            "visible": self.visible,
            "avatarId": self.avatar_id,
            "presence": self.presence,
            "emotion": self.emotion,
            "expression": self.expression,
            "animation": self.animation,
            "animationLoop": self.animation_loop,
            "animationSpeed": self.animation_speed,
            "gazeTarget": self.gaze_target,
            "speaking": self.speaking,
            "lipsyncActive": self.lipsync_active,
            "position": list(self.position),
            "rotation": list(self.rotation),
            "scale": self.scale,
            "framing": self.framing,
        }


@dataclasses.dataclass(frozen=True)
class AvatarCommand:
    op: str


def _require_mapping(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise AvatarProtocolError("request payload must be a JSON object")
    return payload


def _require_fields(payload: Mapping[str, Any], required: set[str]) -> None:
    missing = required - set(payload)
    if missing:
        raise AvatarProtocolError(
            "missing required field(s): " + ", ".join(sorted(missing))
        )
    unexpected = set(payload) - required
    if unexpected:
        raise AvatarProtocolError(
            "unexpected request field(s): " + ", ".join(sorted(unexpected))
        )


def _enum_field(payload: Mapping[str, Any], key: str, values: tuple[str, ...]) -> str:
    value = payload[key]
    if not isinstance(value, str) or value not in values:
        raise AvatarProtocolError(
            f"{key} must be one of: " + ", ".join(values)
        )
    return value


def _number_field(payload: Mapping[str, Any], key: str, minimum: float, maximum: float) -> float:
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AvatarProtocolError(f"{key} must be a number")
    number = float(value)
    if not minimum <= number <= maximum:
        raise AvatarProtocolError(
            f"{key} must be between {minimum} and {maximum}"
        )
    return number


def _vector_field(
    payload: Mapping[str, Any], key: str, size: int, minimum: float, maximum: float
) -> tuple[float, ...]:
    value = payload[key]
    if not isinstance(value, (list, tuple)) or len(value) != size:
        raise AvatarProtocolError(f"{key} must be a list of {size} numbers")
    numbers = []
    for item in value:
        if isinstance(item, bool) or not isinstance(item, (int, float)):
            raise AvatarProtocolError(f"{key} must be a list of {size} numbers")
        number = float(item)
        if not minimum <= number <= maximum:
            raise AvatarProtocolError(
                f"{key} values must be between {minimum} and {maximum}"
            )
        numbers.append(number)
    return tuple(numbers)


def _text_field(payload: Mapping[str, Any], key: str, maximum: int) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise AvatarProtocolError(f"{key} must be a string")
    text = value.strip()
    if not text or len(text) > maximum:
        raise AvatarProtocolError(
            f"{key} must contain 1 to {maximum} characters"
        )
    return text


def _avatar_id_field(payload: Mapping[str, Any]) -> str:
    value = payload["avatarId"]
    if not isinstance(value, str):
        raise AvatarProtocolError("avatarId must be a string")
    avatar_id = value.strip()
    if not avatar_id or len(avatar_id) > 128:
        raise AvatarProtocolError("avatarId must contain 1 to 128 characters")
    if any(character not in _AVATAR_ID_CHARACTERS for character in avatar_id):
        raise AvatarProtocolError(
            "avatarId may contain lowercase letters, digits, '.' '_' and '-'"
        )
    return avatar_id


_AVATAR_ID_CHARACTERS = set("abcdefghijklmnopqrstuvwxyz0123456789._-")


@dataclasses.dataclass(frozen=True)
class PresenceSet(AvatarCommand):
    presence: str = "idle"


@dataclasses.dataclass(frozen=True)
class EmotionSet(AvatarCommand):
    emotion: str = "neutral"


@dataclasses.dataclass(frozen=True)
class ExpressionSet(AvatarCommand):
    expression: str = "neutral"


@dataclasses.dataclass(frozen=True)
class GestureTrigger(AvatarCommand):
    gesture: str = "wave"


@dataclasses.dataclass(frozen=True)
class AnimationPlay(AvatarCommand):
    animation: str = "idle"
    loop: bool = False
    speed: float = 1.0
    duration: Optional[float] = None


@dataclasses.dataclass(frozen=True)
class GazeSet(AvatarCommand):
    target: object = "auto"


@dataclasses.dataclass(frozen=True)
class SpeechBegin(AvatarCommand):
    pass


@dataclasses.dataclass(frozen=True)
class SpeechAudio(AvatarCommand):
    audio: bytes = b""
    sample_rate: int = 16000


@dataclasses.dataclass(frozen=True)
class SpeechEnd(AvatarCommand):
    pass


@dataclasses.dataclass(frozen=True)
class SpeechCancel(AvatarCommand):
    pass


@dataclasses.dataclass(frozen=True)
class TransformSet(AvatarCommand):
    position: Optional[tuple[float, float, float]] = None
    rotation: Optional[tuple[float, float, float]] = None
    scale: Optional[float] = None


@dataclasses.dataclass(frozen=True)
class FramingSet(AvatarCommand):
    framing: str = "half"


@dataclasses.dataclass(frozen=True)
class AvatarIdCommand(AvatarCommand):
    avatar_id: str = ""


@dataclasses.dataclass(frozen=True)
class AvatarImport(AvatarCommand):
    name: str = ""
    data: Optional[bytes] = None
    path: Optional[str] = None


@dataclasses.dataclass(frozen=True)
class SimpleCommand(AvatarCommand):
    pass


def _no_payload(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    _require_fields(payload, set())
    return payload


def _parse_presence_set(payload: Mapping[str, Any]) -> AvatarCommand:
    payload = _require_mapping(payload)
    _require_fields(payload, {"presence"})
    return PresenceSet(
        op="avatar.presence.set",
        presence=_enum_field(payload, "presence", PRESENCES),
    )


def _parse_emotion_set(payload: Mapping[str, Any]) -> AvatarCommand:
    payload = _require_mapping(payload)
    _require_fields(payload, {"emotion"})
    return EmotionSet(
        op="avatar.emotion.set",
        emotion=_enum_field(payload, "emotion", EMOTIONS),
    )


def _parse_expression_set(payload: Mapping[str, Any]) -> AvatarCommand:
    payload = _require_mapping(payload)
    _require_fields(payload, {"expression"})
    return ExpressionSet(
        op="avatar.expression.set",
        expression=_enum_field(payload, "expression", EXPRESSIONS),
    )


def _parse_gesture(payload: Mapping[str, Any]) -> AvatarCommand:
    payload = _require_mapping(payload)
    _require_fields(payload, {"gesture"})
    return GestureTrigger(
        op="avatar.gesture", gesture=_enum_field(payload, "gesture", GESTURES)
    )


def _parse_animation_play(payload: Mapping[str, Any]) -> AvatarCommand:
    payload = _require_mapping(payload)
    required = {"animation", "loop", "speed", "duration"}
    unexpected = set(payload) - required
    if unexpected:
        raise AvatarProtocolError(
            "unexpected request field(s): " + ", ".join(sorted(unexpected))
        )
    animation = _enum_field(payload, "animation", SEMANTIC_ANIMATIONS)
    loop = payload.get("loop", False)
    if not isinstance(loop, bool):
        raise AvatarProtocolError("loop must be a boolean")
    speed = _number_field(payload, "speed", MIN_SPEED, MAX_SPEED) if "speed" in payload else 1.0
    duration = None
    if "duration" in payload:
        duration = _number_field(payload, "duration", MIN_DURATION, MAX_DURATION)
    return AnimationPlay(
        op="avatar.animation.play",
        animation=animation,
        loop=loop,
        speed=speed,
        duration=duration,
    )


def _parse_gaze_set(payload: Mapping[str, Any]) -> AvatarCommand:
    payload = _require_mapping(payload)
    _require_fields(payload, {"target"})
    target = payload["target"]
    if isinstance(target, str):
        if target not in ("user", "auto", "center"):
            raise AvatarProtocolError(
                "target must be 'user', 'auto', 'center' or a point object"
            )
        return GazeSet(op="avatar.gaze.set", target=target)
    if isinstance(target, Mapping):
        required = {"x", "y", "z"}
        if set(target) != required:
            raise AvatarProtocolError("target point must contain exactly x, y, z")
        vector = _vector_field(
            {"v": [target["x"], target["y"], target["z"]]}, "v", 3, -1000.0, 1000.0
        )
        return GazeSet(op="avatar.gaze.set", target=vector)
    raise AvatarProtocolError(
        "target must be 'user', 'auto', 'center' or a point object"
    )


def _parse_speech_audio(payload: Mapping[str, Any]) -> AvatarCommand:
    payload = _require_mapping(payload)
    unexpected = set(payload) - {"audio", "sampleRate"}
    if unexpected:
        raise AvatarProtocolError(
            "unexpected request field(s): " + ", ".join(sorted(unexpected))
        )
    if "audio" not in payload:
        raise AvatarProtocolError("missing required field(s): audio")
    raw = base64_decode(payload["audio"])
    sample_rate = 16000
    if "sampleRate" in payload:
        value = payload["sampleRate"]
        if isinstance(value, bool) or not isinstance(value, int):
            raise AvatarProtocolError("sampleRate must be an integer")
        if not 1 <= value <= MAX_SAMPLE_RATE:
            raise AvatarProtocolError(
                f"sampleRate must be between 1 and {MAX_SAMPLE_RATE}"
            )
        sample_rate = value
    return SpeechAudio(op="avatar.speech.audio", audio=raw, sample_rate=sample_rate)


def _parse_transform_set(payload: Mapping[str, Any]) -> AvatarCommand:
    payload = _require_mapping(payload)
    allowed = {"position", "rotation", "scale"}
    unexpected = set(payload) - allowed
    if unexpected:
        raise AvatarProtocolError(
            "unexpected request field(s): " + ", ".join(sorted(unexpected))
        )
    if not payload:
        raise AvatarProtocolError(
            "at least one of position, rotation, scale is required"
        )
    position = None
    rotation = None
    scale = None
    if "position" in payload:
        position = _vector_field(payload, "position", 3, -MAX_AXIS, MAX_AXIS)  # type: ignore[assignment]
    if "rotation" in payload:
        rotation = _vector_field(payload, "rotation", 3, -MAX_ROTATION, MAX_ROTATION)  # type: ignore[assignment]
    if "scale" in payload:
        scale = _number_field(payload, "scale", MIN_SCALE, MAX_SCALE)
    return TransformSet(
        op="avatar.transform.set", position=position, rotation=rotation, scale=scale
    )


def _parse_framing_set(payload: Mapping[str, Any]) -> AvatarCommand:
    payload = _require_mapping(payload)
    _require_fields(payload, {"framing"})
    return FramingSet(
        op="avatar.framing.set", framing=_enum_field(payload, "framing", FRAMINGS)
    )


def _parse_avatar_id(op: str, payload: Mapping[str, Any]) -> AvatarCommand:
    payload = _require_mapping(payload)
    _require_fields(payload, {"avatarId"})
    return AvatarIdCommand(op=op, avatar_id=_avatar_id_field(payload))


def _parse_avatar_import(payload: Mapping[str, Any]) -> AvatarCommand:
    payload = _require_mapping(payload)
    allowed = {"name", "data", "path"}
    unexpected = set(payload) - allowed
    if unexpected:
        raise AvatarProtocolError(
            "unexpected request field(s): " + ", ".join(sorted(unexpected))
        )
    if "name" not in payload:
        raise AvatarProtocolError("missing required field(s): name")
    name = _text_field(payload, "name", MAX_NAME)
    has_data = "data" in payload
    has_path = "path" in payload
    if has_data and has_path:
        raise AvatarProtocolError("provide either data or path, not both")
    if not has_data and not has_path:
        raise AvatarProtocolError("either data or path is required")
    data = None
    path = None
    if has_data:
        data = base64_decode(payload["data"])
    if has_path:
        path = payload["path"]
        if not isinstance(path, str) or not path.strip():
            raise AvatarProtocolError("path must be a non-empty string")
    return AvatarImport(op="avatar.import", name=name, data=data, path=path)


_EMPTY_OPS = {
    "avatar.status",
    "avatar.list",
    "avatar.transform.get",
    "avatar.framing.get",
    "avatar.unload",
    "avatar.show",
    "avatar.hide",
    "avatar.animation.stop",
    "avatar.speech.begin",
    "avatar.speech.end",
    "avatar.speech.cancel",
}

_ENUM_PARSERS = {
    "avatar.presence.set": _parse_presence_set,
    "avatar.emotion.set": _parse_emotion_set,
    "avatar.expression.set": _parse_expression_set,
    "avatar.gesture": _parse_gesture,
    "avatar.framing.set": _parse_framing_set,
}


def parse_command(op: str, payload: Mapping[str, Any]) -> AvatarCommand:
    """Parse and validate one avatar protocol operation."""
    if not isinstance(op, str) or not op:
        raise AvatarProtocolError("operation name must be a non-empty string")
    payload = _require_mapping(payload)
    if op in _EMPTY_OPS:
        _no_payload(payload)
        return SimpleCommand(op=op)
    if op in _ENUM_PARSERS:
        return _ENUM_PARSERS[op](payload)
    if op == "avatar.animation.play":
        return _parse_animation_play(payload)
    if op == "avatar.gaze.set":
        return _parse_gaze_set(payload)
    if op == "avatar.speech.audio":
        return _parse_speech_audio(payload)
    if op == "avatar.transform.set":
        return _parse_transform_set(payload)
    if op in ("avatar.load", "avatar.select", "avatar.delete"):
        return _parse_avatar_id(op, payload)
    if op == "avatar.import":
        return _parse_avatar_import(payload)
    raise AvatarProtocolError(f"unknown avatar operation {op!r}")


# ---------------------------------------------------------------------------
# AvatarActor: the serialized authority
# ---------------------------------------------------------------------------

RUNTIME_PRESENCE_EVENTS = {
    "turn.started": "thinking",
    "turn.cancelled": "idle",
    "assistant.completed": "idle",
    "agent.completed": "idle",
    "agent.failed": "idle",
    "assistant.failed": "idle",
    "runtime.started": "idle",
    "runtime.stopped": "idle",
    "runtime.idle": "idle",
}


class ActorCommandError(Exception):
    """An avatar operation failed; the message is safe to show clients."""


class ActorUnavailable(Exception):
    """The actor is stopped or overloaded."""


_AVATAR_OP_HANDLERS: dict = {}


class AvatarActor:
    """Single-writer authority for all avatar presentation state.

    HTTP handlers, event pumps, and timers enqueue work; only the actor
    worker mutates state or talks to the renderer. Renderer outages degrade
    presentation but never break Zara semantics: emotion, presence, and
    speech lifecycle always update typed state.
    """

    def __init__(
        self,
        *,
        library: AvatarLibrary,
        renderer_factory,
        analyzer_factory=None,
        seed: int = 7,
        crossfade: float = DEFAULT_CROSSFADE,
        durations: Optional[Mapping[str, float]] = None,
        restart_backoff: float = 1.0,
        max_restarts: int = 3,
        renderer_load_timeout: float = 20.0,
        queue_size: int = 256,
        clock=time.monotonic,
    ) -> None:
        self._library = library
        self._renderer_factory = renderer_factory
        self._renderer = None
        self._state = AvatarState()
        self._controller = AnimationController(
            crossfade=crossfade, seed=seed, durations=durations
        )
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._events: queue.Queue = queue.Queue(maxsize=queue_size)
        self._analyzer_factory = analyzer_factory or VisemeAnalyzer
        self._analyzer: Optional[VisemeAnalyzer] = None
        self._available_expressions: frozenset = frozenset()
        self._animation_deadline: Optional[float] = None
        self._restart_backoff = restart_backoff
        self._max_restarts = max_restarts
        self._renderer_load_timeout = renderer_load_timeout
        self._restart_attempts = 0
        self._clock = clock
        self._renderer_state = "new"
        self._presence_explicit = False
        self._presence_before_speech: Optional[str] = None
        self._selected_avatar_id: Optional[str] = None
        self._stopping = False
        self._worker_done = threading.Event()

    # -- client API (thread-safe) -------------------------------------------

    def submit_async(self, command: AvatarCommand):
        if self._stopping:
            raise ActorUnavailable("avatar actor is stopped")
        future: concurrent.futures.Future = concurrent.futures.Future()
        try:
            self._queue.put(("command", command, future), timeout=1.0)
        except queue.Full:
            future.set_exception(ActorUnavailable("avatar actor is overloaded"))
        return future

    def submit(self, command: AvatarCommand, *, timeout: float = 5.0):
        future = self.submit_async(command)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as error:
            raise ActorCommandError("avatar actor did not respond in time") from error

    def handle_runtime_event(self, name: str, data: Optional[Mapping] = None) -> None:
        try:
            self._queue.put(("runtime", name, data), timeout=1.0)
        except queue.Full:
            pass

    def handle_renderer_exit(self) -> None:
        try:
            self._queue.put(("renderer_exit", None, None), timeout=1.0)
        except queue.Full:
            pass

    def request_renderer_probe(self) -> None:
        try:
            self._queue.put(("probe", None, None), timeout=1.0)
        except queue.Full:
            pass

    def status(self) -> dict:
        state = self._state
        document = state.to_document()
        document["renderer"] = {"state": self._renderer_state}
        document["selectedAvatarId"] = self._selected_avatar_id
        return document

    def flush(self, timeout: float = 5.0) -> None:
        """Block until every previously enqueued item has been processed.

        The queue is FIFO with a single worker, so completing a sentinel
        status command ordered-after earlier items guarantees completion.
        """
        self.submit(parse_command("avatar.status", {}), timeout=timeout)

    def available_expressions(self) -> tuple:
        return tuple(self._available_expressions)

    def drain_state_events(self, limit: int = 64) -> list:
        events = []
        while len(events) < limit:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    # -- worker loop ---------------------------------------------------------

    def run(self, stop_event: threading.Event) -> None:
        while not stop_event.is_set() and not self._stopping:
            timeout = self._loop_timeout()
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                item = None
            self._poll_renderer_events()
            if item is None:
                self._check_animation_deadline()
                continue
            kind, payload, extra = item
            if kind == "command":
                self._execute(payload, extra)
            elif kind == "runtime":
                self._apply_runtime_event(payload, extra)
            elif kind == "renderer_exit":
                self._recover_renderer()
            elif kind == "probe":
                self._ensure_renderer()
        self._worker_done.set()

    def shutdown(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        self._worker_done.wait(timeout=5.0)
        self._close_renderer()

    # -- command execution ----------------------------------------------------

    def _execute(self, command: AvatarCommand, future) -> None:
        try:
            result = self._dispatch(command)
        except Exception as error:
            future.set_exception(error)
        else:
            future.set_result(result)
            self._publish("avatar.state_changed")

    def _dispatch(self, command: AvatarCommand):
        op = command.op
        if op == "avatar.status":
            return self.status()
        if op == "avatar.list":
            return {
                "avatars": [
                    record.to_document() for record in self._library.list_avatars()
                ]
            }
        if op == "avatar.transform.get":
            state = self._state
            return {
                "position": list(state.position),
                "rotation": list(state.rotation),
                "scale": state.scale,
            }
        if op == "avatar.framing.get":
            return {"framing": self._state.framing}
        if op == "avatar.presence.set":
            self._state = dataclasses.replace(
                self._state, presence=command.presence
            )
            # An explicit idle resets ownership so runtime inference resumes.
            self._presence_explicit = command.presence != "idle"
            return {"presence": command.presence}
        if op == "avatar.emotion.set":
            self._set_emotion(command.emotion)
            return {"emotion": command.emotion}
        if op == "avatar.expression.set":
            self._apply_expression(command.expression)
            return {"expression": self._state.expression}
        if op == "avatar.gesture":
            self._start_animation_commands(self._controller.gesture(command.gesture))
            return {"animation": self._state.animation}
        if op == "avatar.animation.play":
            commands = self._controller.play(
                command.animation,
                loop=command.loop,
                speed=command.speed,
                duration=command.duration,
            )
            if commands:
                self._start_animation_commands(commands)
            return {"animation": self._state.animation}
        if op == "avatar.animation.stop":
            self._start_animation_commands(self._controller.stop())
            return {"animation": self._state.animation}
        if op == "avatar.gaze.set":
            return self._set_gaze(command.target)
        if op == "avatar.speech.begin":
            return self._speech_begin()
        if op == "avatar.speech.audio":
            return self._speech_audio(command)
        if op == "avatar.speech.end":
            return self._speech_close(cancelled=False)
        if op == "avatar.speech.cancel":
            return self._speech_close(cancelled=True)
        if op == "avatar.transform.set":
            return self._set_transform(command)
        if op == "avatar.framing.set":
            self._state = dataclasses.replace(self._state, framing=command.framing)
            self._renderer_command("SetCamera", {"framing": command.framing})
            return {"framing": command.framing}
        if op == "avatar.unload":
            return self._unload()
        if op == "avatar.show":
            return self._show()
        if op == "avatar.hide":
            self._state = dataclasses.replace(self._state, visible=False)
            self._renderer_command("HideWindow", {})
            return {"visible": False}
        if op in ("avatar.load", "avatar.select"):
            return self._load(command.avatar_id, select=op == "avatar.select")
        if op == "avatar.delete":
            return self._delete(command.avatar_id)
        if op == "avatar.import":
            return self._import(command)
        raise ActorCommandError(f"unsupported operation {op!r}")

    # -- semantics ------------------------------------------------------------

    def _set_emotion(self, emotion: str) -> None:
        self._state = dataclasses.replace(self._state, emotion=emotion)
        self._apply_expression(expression_for_emotion(emotion), explicit=False)

    def _apply_expression(self, requested: str, explicit: bool = True) -> None:
        if self._available_expressions:
            resolved = resolve_expression(requested, self._available_expressions)
        elif requested in EXPRESSION_FALLBACKS:
            # No capability information yet (avatar not loaded): present the
            # requested semantic expression optimistically; the renderer maps
            # or ignores it per model.
            resolved = requested
        else:
            resolved = "neutral"
        self._state = dataclasses.replace(self._state, expression=resolved)
        self._renderer_command("SetExpression", {"name": resolved})

    def _apply_runtime_event(self, name: str, data) -> None:
        if name == "speech.state_changed" and isinstance(data, Mapping):
            voice_state = data.get("state")
            if voice_state == "listening":
                self._set_inferred_presence("listening")
            return
        presence = RUNTIME_PRESENCE_EVENTS.get(name)
        if presence is not None:
            self._set_inferred_presence(presence)

    def _set_inferred_presence(self, presence: str) -> None:
        if self._presence_explicit or self._state.speaking:
            return
        self._state = dataclasses.replace(self._state, presence=presence)

    def _set_gaze(self, target) -> dict:
        if isinstance(target, str):
            canonical = target
        else:
            canonical = "point"
        self._state = dataclasses.replace(self._state, gaze_target=canonical)
        params = (
            {"target": target}
            if isinstance(target, str)
            else {"point": list(target)}
        )
        self._renderer_command("SetGaze", params)
        return {"gazeTarget": canonical}

    # -- animation ------------------------------------------------------------

    def _start_animation_commands(self, commands) -> None:
        for command in commands:
            self._renderer_command(
                "PlayAnimation",
                {
                    "clip": command.clip,
                    "loop": command.loop,
                    "speed": command.speed,
                    "duration": command.duration,
                    "crossfade": command.crossfade,
                },
            )
            self._state = dataclasses.replace(
                self._state,
                animation=command.clip,
                animation_loop=command.loop,
                animation_speed=command.speed,
            )
            if command.duration is not None and not command.loop:
                self._animation_deadline = self._clock() + command.duration
            else:
                self._animation_deadline = None

    def _loop_timeout(self) -> float:
        if self._animation_deadline is None:
            return 0.25
        remaining = self._animation_deadline - self._clock()
        return max(0.01, min(0.25, remaining))

    def _check_animation_deadline(self) -> None:
        if self._animation_deadline is None:
            return
        if self._clock() < self._animation_deadline:
            return
        self._animation_deadline = None
        if self._controller.current is None:
            return
        commands = self._controller.finish()
        if commands:
            self._start_animation_commands(commands)

    # -- speech -----------------------------------------------------------------

    def _speech_begin(self) -> dict:
        if not self._state.speaking:
            self._presence_before_speech = self._state.presence
            self._analyzer = self._analyzer_factory()
        self._state = dataclasses.replace(
            self._state,
            speaking=True,
            lipsync_active=False,
            presence="speaking",
        )
        return {"speaking": True}

    def _speech_audio(self, command: SpeechAudio) -> dict:
        if not self._state.speaking or self._analyzer is None:
            raise ActorCommandError("speech.audio requires an active speech session")
        frame = self._analyzer.process(
            command.audio, sample_rate=command.sample_rate
        )
        weights = frame.to_document()
        self._renderer_command("SetVisemes", {"weights": weights})
        self._state = dataclasses.replace(self._state, lipsync_active=True)
        return {"visemes": weights, "amplitude": round(frame.amplitude, 4)}

    def _speech_close(self, *, cancelled: bool) -> dict:
        zeros = {name: 0.0 for name in VISEMES}
        self._renderer_command("SetVisemes", {"weights": zeros})
        if self._analyzer is not None:
            self._analyzer.reset()
        self._analyzer = None
        presence = self._presence_before_speech or "idle"
        self._presence_before_speech = None
        if not self._presence_explicit:
            presence = "idle" if cancelled else presence
        self._state = dataclasses.replace(
            self._state,
            speaking=False,
            lipsync_active=False,
            presence=presence,
        )
        return {"speaking": False, "cancelled": cancelled}

    # -- avatars -------------------------------------------------------------------

    def _load(self, avatar_id: str, *, select: bool) -> dict:
        record = self._library.get(avatar_id)
        if record is None:
            raise ActorCommandError(f"unknown avatar {avatar_id!r}")
        self._require_renderer()
        if self._state.loaded and self._state.avatar_id != avatar_id:
            self._renderer_command("UnloadAvatar", {})
        try:
            result = self._renderer_request(
                "LoadAvatar",
                {
                    "avatarId": record.avatar_id,
                    "path": str(record.path),
                    "seed": 7,
                },
                timeout=self._renderer_load_timeout,
            )
        except RendererRequestError as error:
            self._renderer_state = "unavailable"
            raise ActorCommandError(
                f"renderer rejected avatar {avatar_id!r}: {error}"
            ) from error
        expressions = result.get("expressions")
        if isinstance(expressions, list):
            self._available_expressions = frozenset(
                name for name in expressions if isinstance(name, str)
            )
        self._controller.reset()
        self._animation_deadline = None
        self._state = dataclasses.replace(
            self._state, loaded=True, avatar_id=record.avatar_id
        )
        if select:
            self._selected_avatar_id = record.avatar_id
            self._library.mark_selected(record.avatar_id)
        self._apply_expression(self._state.expression)
        self._renderer_command(
            "SetTransform",
            {
                "position": list(self._state.position),
                "rotation": list(self._state.rotation),
                "scale": self._state.scale,
            },
        )
        self._renderer_command("SetCamera", {"framing": self._state.framing})
        self._start_animation_commands(self._controller.play("idle"))
        return {"avatarId": record.avatar_id, "loaded": True}

    def _unload(self) -> dict:
        self._renderer_command("UnloadAvatar", {})
        self._controller.reset()
        self._animation_deadline = None
        self._state = dataclasses.replace(
            self._state, loaded=False, visible=False, avatar_id=None, animation=None
        )
        return {"loaded": False}

    def _show(self) -> dict:
        if not self._state.loaded:
            raise ActorCommandError("load an avatar before showing it")
        self._renderer_command("ShowWindow", {})
        self._state = dataclasses.replace(self._state, visible=True)
        if self._state.animation is None:
            self._start_animation_commands(self._controller.play("idle"))
        return {"visible": True}

    def _delete(self, avatar_id: str) -> dict:
        if self._state.loaded and self._state.avatar_id == avatar_id:
            self._unload()
        try:
            self._library.delete(avatar_id)
        except KeyError:
            raise ActorCommandError(f"unknown avatar {avatar_id!r}") from None
        if self._selected_avatar_id == avatar_id:
            self._selected_avatar_id = None
        return {"deleted": avatar_id}

    def _import(self, command: AvatarImport) -> dict:
        try:
            if command.data is not None:
                record = self._library.import_avatar(command.name, command.data)
            else:
                record = self._library.import_from_path(command.name, command.path)
        except InvalidVrmError as error:
            raise ActorCommandError(f"invalid VRM: {error}") from error
        except FileNotFoundError as error:
            raise ActorCommandError(f"avatar file not found: {error}") from error
        except OSError as error:
            raise ActorCommandError(f"avatar file unreadable: {error}") from error
        return record.to_document()

    def _set_transform(self, command: TransformSet) -> dict:
        state = self._state
        if command.position is not None:
            state = dataclasses.replace(state, position=command.position)
        if command.rotation is not None:
            state = dataclasses.replace(state, rotation=command.rotation)
        if command.scale is not None:
            state = dataclasses.replace(state, scale=command.scale)
        self._state = state
        self._renderer_command(
            "SetTransform",
            {
                "position": list(state.position),
                "rotation": list(state.rotation),
                "scale": state.scale,
            },
        )
        return {
            "position": list(state.position),
            "rotation": list(state.rotation),
            "scale": state.scale,
        }

    # -- renderer management ------------------------------------------------------

    def _require_renderer(self) -> None:
        if not self._ensure_renderer():
            raise AvatarRendererUnavailable(
                "renderer is unavailable; avatar presentation is degraded"
            )

    def _ensure_renderer(self) -> bool:
        if self._renderer is None:
            try:
                self._renderer = self._renderer_factory()
            except RendererUnavailable:
                self._renderer_state = "unavailable"
                return False
        if self._renderer.is_running:
            self._renderer_state = "running"
            self._restart_attempts = 0
            return True
        try:
            self._renderer.start()
        except (RendererUnavailable, RuntimeError):
            # A host whose startup already failed cannot be restarted in
            # place; drop it so the next attempt builds a fresh one and
            # degrade presentation now.
            self._renderer = None
            self._renderer_state = "unavailable"
            return False
        if not self._renderer.is_running:
            self._renderer_state = "unavailable"
            return False
        self._renderer_state = "running"
        self._restart_attempts = 0
        return True

    def _renderer_command(self, command: str, params: dict) -> None:
        if not self._ensure_renderer():
            return
        self._renderer_request(command, params)

    def _renderer_request(
        self, command: str, params: dict, *, timeout: Optional[float] = None
    ) -> dict:
        try:
            return self._renderer.request(command, params, timeout=timeout)
        except RendererRequestError as error:
            if not self._renderer.is_running:
                self._renderer_state = "unavailable"
            raise

    def _poll_renderer_events(self) -> None:
        if self._renderer is None:
            return
        for event in self._renderer.drain_events():
            name = event.get("event")
            if name == "rendererExited":
                self._renderer_state = "unavailable"
                self._recover_renderer()

    def _recover_renderer(self) -> None:
        if self._restart_attempts >= self._max_restarts:
            self._renderer_state = "unavailable"
            return
        self._restart_attempts += 1
        if self._restart_backoff:
            time.sleep(self._restart_backoff)
        try:
            self._renderer.restart()
        except (RendererUnavailable, AttributeError):
            self._renderer_state = "unavailable"
            return
        self._renderer_state = "running"
        self._resync_renderer()

    def _resync_renderer(self) -> None:
        state = self._state
        if state.loaded and state.avatar_id:
            record = self._library.get(state.avatar_id)
            if record is not None:
                try:
                    result = self._renderer_request(
                        "LoadAvatar",
                        {
                            "avatarId": record.avatar_id,
                            "path": str(record.path),
                            "seed": 7,
                        },
                        timeout=self._renderer_load_timeout,
                    )
                    expressions = result.get("expressions")
                    if isinstance(expressions, list):
                        self._available_expressions = frozenset(
                            name
                            for name in expressions
                            if isinstance(name, str)
                        )
                except RendererRequestError:
                    self._renderer_state = "unavailable"
                    return
        self._renderer_command("SetExpression", {"name": state.expression})
        self._renderer_command(
            "SetTransform",
            {
                "position": list(state.position),
                "rotation": list(state.rotation),
                "scale": state.scale,
            },
        )
        self._renderer_command("SetCamera", {"framing": state.framing})

    def _close_renderer(self) -> None:
        if self._renderer is not None:
            try:
                self._renderer.shutdown()
            except Exception:
                pass

    def _publish(self, kind: str) -> None:
        try:
            self._events.put(
                {"type": kind, "state": self._state.to_document()}, timeout=0.1
            )
        except queue.Full:
            try:
                self._events.get_nowait()
            except queue.Empty:
                pass
            try:
                self._events.put(
                    {"type": kind, "state": self._state.to_document()}, timeout=0.1
                )
            except queue.Full:
                pass


# ---------------------------------------------------------------------------
# ZaraAvatarPlugin: Zara service-plugin surface
# ---------------------------------------------------------------------------


def _event_name(event: object) -> str:
    """Serialize a runtime event class name into a stable dotted name."""
    name = type(event).__name__
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()
    families = {
        "runtime": "runtime",
        "turn": "turn",
        "agent": "assistant",
        "assistant": "assistant",
        "response": "assistant",
        "output": "assistant",
        "voice": "speech",
        "transcript": "speech",
        "intent": "intent",
        "prolog": "intent",
        "tool": "tool",
        "user": "user",
    }
    for prefix, family in families.items():
        if snake.startswith(prefix + "_"):
            return f"{family}.{snake[len(prefix) + 1:]}"
    return f"runtime.{snake}"


_HTTP_ROUTES: dict[tuple[str, str], str] = {
    ("GET", "/v1/avatar/status"): "avatar.status",
    ("GET", "/v1/avatar/list"): "avatar.list",
    ("GET", "/v1/avatar/transform"): "avatar.transform.get",
    ("GET", "/v1/avatar/framing"): "avatar.framing.get",
    ("POST", "/v1/avatar/import"): "avatar.import",
    ("POST", "/v1/avatar/delete"): "avatar.delete",
    ("POST", "/v1/avatar/load"): "avatar.load",
    ("POST", "/v1/avatar/unload"): "avatar.unload",
    ("POST", "/v1/avatar/select"): "avatar.select",
    ("POST", "/v1/avatar/show"): "avatar.show",
    ("POST", "/v1/avatar/hide"): "avatar.hide",
    ("POST", "/v1/avatar/presence"): "avatar.presence.set",
    ("POST", "/v1/avatar/emotion"): "avatar.emotion.set",
    ("POST", "/v1/avatar/expression"): "avatar.expression.set",
    ("POST", "/v1/avatar/gesture"): "avatar.gesture",
    ("POST", "/v1/avatar/animation/play"): "avatar.animation.play",
    ("POST", "/v1/avatar/animation/stop"): "avatar.animation.stop",
    ("POST", "/v1/avatar/gaze"): "avatar.gaze.set",
    ("POST", "/v1/avatar/speech/begin"): "avatar.speech.begin",
    ("POST", "/v1/avatar/speech/audio"): "avatar.speech.audio",
    ("POST", "/v1/avatar/speech/end"): "avatar.speech.end",
    ("POST", "/v1/avatar/speech/cancel"): "avatar.speech.cancel",
    ("POST", "/v1/avatar/transform"): "avatar.transform.set",
    ("POST", "/v1/avatar/framing"): "avatar.framing.set",
}

DEFAULT_AVATAR_PORT = 7321
DEFAULT_AVATAR_DIRECTORY = "~/.local/share/zara/avatars"
DEFAULT_REQUEST_SIZE_LIMIT = 1024 * 1024
MAX_REQUEST_SIZE_LIMIT = 8 * 1024 * 1024
DEFAULT_MAX_RENDERER_RESTARTS = 3


class _AvatarRequestError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status


class _AvatarHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address: tuple[str, int], plugin) -> None:
        self.plugin = plugin
        super().__init__(server_address, _AvatarRequestHandler)


class _AvatarRequestHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "ZaraAvatar/0.1"
    sys_version = ""

    @property
    def plugin(self):
        return self.server.plugin

    def log_message(self, format: str, *args: object) -> None:
        return None

    def do_GET(self) -> None:
        if not self._local_client():
            self._send_error(403, "local clients only")
            return
        path = self.path.partition("?")[0]
        if path == "/v1/avatar/events":
            self._serve_events()
            return
        if path == "/v1/avatar/status":
            self._send_json(200, self.plugin.status_document())
            return
        op = _HTTP_ROUTES.get(("GET", path))
        if op is None:
            self._send_error(404, "route not found")
            return
        self._dispatch(op, {})

    def do_POST(self) -> None:
        if not self._local_client():
            self._send_error(403, "local clients only")
            return
        path = self.path.partition("?")[0]
        op = _HTTP_ROUTES.get(("POST", path))
        if op is None:
            self._send_error(404, "route not found")
            return
        try:
            payload = self._read_json()
        except _AvatarRequestError as error:
            self._send_error(error.status, str(error))
            return
        self._dispatch(op, payload)

    def _dispatch(self, op: str, payload: Mapping[str, Any]) -> None:
        try:
            command = parse_command(op, payload)
        except AvatarProtocolError as error:
            self._send_error(400, str(error))
            return
        try:
            result = self.plugin.submit(command)
        except AvatarRendererUnavailable as error:
            self._send_error(503, str(error))
            return
        except ActorCommandError as error:
            self._send_error(400, str(error))
            return
        except ActorUnavailable as error:
            self._send_error(503, str(error))
            return
        except concurrent.futures.TimeoutError:
            self._send_error(504, "avatar actor did not respond in time")
            return
        except Exception as error:
            self._send_error(500, f"avatar internal error: {error}")
            return
        self._send_json(200, result)

    def _serve_events(self) -> None:
        client = self.plugin.add_event_client()
        if client is None:
            self._send_error(503, "event client limit reached")
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("Connection", "close")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            last_write = time.monotonic()
            while not self.plugin.stopping:
                try:
                    sequence, payload = client.get(timeout=0.25)
                except queue.Empty:
                    if time.monotonic() - last_write >= 15.0:
                        self.wfile.write(b": keepalive\n\n")
                        self.wfile.flush()
                        last_write = time.monotonic()
                    continue
                frame = (
                    f"id: {sequence}\n"
                    f"event: avatar.state_changed\n"
                    f"data: {payload}\n\n"
                ).encode("utf-8")
                self.wfile.write(frame)
                self.wfile.flush()
                last_write = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        finally:
            self.plugin.remove_event_client(client)

    def _local_client(self) -> bool:
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

    def _read_json(self) -> dict:
        if self.headers.get_content_type() != "application/json":
            raise _AvatarRequestError(415, "content type must be application/json")
        raw_length = self.headers.get("Content-Length")
        if raw_length is None:
            raise _AvatarRequestError(411, "content length is required")
        try:
            length = int(raw_length)
        except ValueError as error:
            raise _AvatarRequestError(400, "invalid content length") from error
        if length < 0 or length > self.plugin.request_size_limit:
            raise _AvatarRequestError(413, "request body exceeds configured limit")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise _AvatarRequestError(400, "request body must be valid JSON") from error
        if not isinstance(payload, dict):
            raise _AvatarRequestError(400, "request body must be a JSON object")
        return payload

    def _send_error(self, status: int, message: str) -> None:
        self._send_json(status, {"error": " ".join(str(message).split())[:512]})

    def _send_json(self, status: int, document: Mapping[str, Any]) -> None:
        body = json.dumps(document, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)


class AvatarRendererUnavailable(ActorCommandError):
    """The renderer is unavailable; presentation is degraded but alive."""


def _renderer_roots() -> list:
    return [
        Path(__file__).resolve().parent.parent / "renderer",
        Path(DEFAULT_AVATAR_DIRECTORY).expanduser().parent / "renderer",
    ]


def _system_electron_candidates() -> list:
    candidates = [
        str(path) for path in sorted(Path("/usr/lib").glob("electron*/electron"))
    ]
    found = shutil.which("electron")
    if found:
        candidates.append(found)
    return candidates


def _electron_with_working_sandbox(candidates: Optional[list]):
    """The first electron whose chrome-sandbox helper is SUID root.

    Chromium's GPU and render processes refuse to run (and the avatar page
    never loads) when the sandbox helper is missing; hardened systems also
    refuse shared memory to unsandboxed chromium entirely.
    """
    for candidate in candidates or ():
        electron = Path(candidate)
        if not electron.is_file():
            continue
        try:
            mode = (electron.parent / "chrome-sandbox").stat().st_mode
        except OSError:
            continue
        if mode & stat.S_ISUID:
            return electron
    return None


def _resolve_renderer_command(
    configuration: Mapping[str, Any],
    *,
    renderer_roots: Optional[list] = None,
    electron_candidates: Optional[list] = None,
) -> Optional[list]:
    explicit = configuration.get("renderer_command")
    if explicit is not None:
        if (
            not isinstance(explicit, list)
            or not explicit
            or not all(isinstance(part, str) for part in explicit)
        ):
            raise ValueError("renderer_command must be a list of strings")
        return list(explicit)
    env = os.environ.get("ZARA_AVATAR_RENDERER")
    if env:
        parts = env.split()
        if parts:
            return parts
    roots = _renderer_roots() if renderer_roots is None else renderer_roots

    candidates = (
        electron_candidates
        if electron_candidates is not None
        else _system_electron_candidates()
    )
    system = _electron_with_working_sandbox(candidates)
    if system is not None:
        for root in roots:
            if (Path(root) / "main.mjs").is_file():
                return [str(system), str(Path(root) / "main.mjs")]

    for root in roots:
        electron = Path(root) / "node_modules" / ".bin" / "electron"
        if electron.is_file():
            return [str(electron), str(Path(root) / "main.mjs")]
    return None


class ZaraAvatarPlugin(ServicePlugin):
    """Optional presentation plugin: owns the avatar, not the brain."""

    metadata = PluginMetadata(
        name="zara-avatar",
        version=AVATAR_PLUGIN_VERSION,
        api_version=AVATAR_API_VERSION,
        description="Zara-owned 3D avatar presentation (VRM renderer, expression, lip sync)",
    )

    def __init__(self) -> None:
        self._runtime = None
        self._actor: Optional[AvatarActor] = None
        self._library: Optional[AvatarLibrary] = None
        self._server: Optional[_AvatarHTTPServer] = None
        self._subscription = None
        self._event_clients: set = set()
        self._event_clients_lock = threading.RLock()
        self._event_sequence = 0
        self._stopping = threading.Event()
        self._started = False
        self._request_size_limit = DEFAULT_REQUEST_SIZE_LIMIT

    # -- lifecycle ------------------------------------------------------------

    def start(self, runtime) -> None:
        if self._started:
            raise RuntimeError("zara-avatar already started")
        self._started = True
        self._runtime = runtime
        configuration = runtime.configuration
        try:
            self._configure(configuration)
        except Exception:
            self._started = False
            self._stopping.clear()
            raise
        if not self._enabled:
            return
        try:
            self._library = AvatarLibrary(Path(self._avatar_directory).expanduser())
            self._actor = self._build_actor()
            self._server = _AvatarHTTPServer(
                ("127.0.0.1", self._port), self
            )
            self._server.timeout = 0.25
            self._subscription = runtime.subscribe(maxsize=128)
            runtime.start_worker("avatar-actor", self._actor.run)
            runtime.start_worker("avatar-event-pump", self._pump_events)
            runtime.start_worker("avatar-http-server", self._serve)
            # Probe the renderer once so status reflects reality; failure is
            # non-fatal by design. The probe runs on the actor thread because
            # renderer startup may outlive the plugin manager's lifecycle
            # timeout, and blocking start() on it reads as a startup crash.
            self._actor.request_renderer_probe()
        except Exception:
            self._started = False
            self._stopping.set()
            if self._subscription is not None:
                self._subscription.close()
            if self._actor is not None:
                self._actor.shutdown()
            if self._server is not None:
                self._server.server_close()
            self._stopping.clear()
            raise

    def stop(self) -> None:
        if self._stopping.is_set():
            return
        self._stopping.set()
        if self._subscription is not None:
            self._subscription.close()
        if self._actor is not None:
            self._actor.shutdown()

    # -- agent tools ----------------------------------------------------------

    def tools(self) -> tuple:
        from langchain_core.tools import StructuredTool
        from pydantic import BaseModel, Field

        plugin = self

        class ImportArgs(BaseModel):
            path: str = Field(..., description="Absolute path to a local .vrm file.")
            name: Optional[str] = Field(
                default=None,
                description="Display name for the avatar; defaults to the file name.",
            )

        class SelectArgs(BaseModel):
            avatar_id: Optional[str] = Field(
                default=None,
                description="Exact avatarId as reported by zara_avatar_list.",
            )
            name: Optional[str] = Field(
                default=None,
                description=(
                    "Display name of an imported avatar; matched case-insensitively."
                ),
            )

        def _submit(op: str, payload: dict) -> dict:
            if not plugin._started or plugin._actor is None:
                raise ActorUnavailable("zara-avatar plugin is not running")
            return plugin._actor.submit(parse_command(op, payload), timeout=30.0)

        def zara_avatar_import(path: str, name: Optional[str] = None) -> str:
            """Import a local .vrm avatar file, select it, and show it."""
            source = Path(str(path)).expanduser()
            if not source.is_absolute():
                return "error: avatar path must be absolute"
            display_name = str(name).strip() if name and str(name).strip() else source.stem
            try:
                record = _submit(
                    "avatar.import",
                    {"name": display_name, "path": str(source)},
                )
            except Exception as error:
                return f"error: could not import {source}: {error}"
            avatar_id = str(record.get("avatarId", ""))
            try:
                _submit("avatar.select", {"avatarId": avatar_id})
                _submit("avatar.show", {})
            except Exception as error:
                return (
                    f"Imported avatar {display_name!r} (id {avatar_id}) but "
                    f"could not display it: {error}"
                )
            return (
                f"Avatar {display_name!r} imported, selected, and displayed "
                f"(id {avatar_id})."
            )

        def zara_avatar_list() -> str:
            """List imported Zara avatars and which one is selected."""
            try:
                documents = _submit("avatar.list", {}).get("avatars", [])
                status = _submit("avatar.status", {})
            except Exception as error:
                return f"error: {error}"
            if not documents:
                return "No avatars imported yet. Import one with zara_avatar_import."
            selected = status.get("selectedAvatarId")
            lines = []
            for document in documents:
                marker = " (selected)" if document.get("avatarId") == selected else ""
                lines.append(
                    f"- {document.get('name')!r} id={document.get('avatarId')} "
                    f"vrm={document.get('vrmVersion')}{marker}"
                )
            return "\n".join(lines)

        def zara_avatar_select(
            avatar_id: Optional[str] = None, name: Optional[str] = None
        ) -> str:
            """Select and display an already-imported Zara avatar by id or name."""
            if bool(avatar_id) == bool(name):
                return "error: provide exactly one of avatar_id or name"
            try:
                target = str(avatar_id).strip() if avatar_id else None
                if target is None:
                    wanted = str(name).strip().lower()
                    matches = [
                        document
                        for document in _submit("avatar.list", {}).get("avatars", [])
                        if str(document.get("name", "")).strip().lower() == wanted
                    ]
                    if not matches:
                        return (
                            f"error: no avatar named {name!r}; call "
                            "zara_avatar_list for the available ids"
                        )
                    if len(matches) > 1:
                        identifiers = ", ".join(
                            str(document.get("avatarId")) for document in matches
                        )
                        return (
                            f"error: several avatars are named {name!r} "
                            f"({identifiers}); call zara_avatar_select with an "
                            "avatar_id"
                        )
                    target = str(matches[0].get("avatarId"))
                _submit("avatar.select", {"avatarId": target})
                _submit("avatar.show", {})
            except Exception as error:
                return f"error: {error}"
            return f"Avatar {target} selected and displayed."

        return (
            StructuredTool.from_function(
                zara_avatar_import,
                name="zara_avatar_import",
                description=(
                    "Import a local .vrm 3D avatar file for Zara, make it the "
                    "selected avatar, and show it. Use this whenever the user "
                    "gives you the path to a .vrm file they want as their "
                    "avatar. The path must be absolute."
                ),
                args_schema=ImportArgs,
            ),
            StructuredTool.from_function(
                zara_avatar_list,
                name="zara_avatar_list",
                description=(
                    "List the Zara avatars that have been imported so far, "
                    "including their ids and which one is currently selected."
                ),
            ),
            StructuredTool.from_function(
                zara_avatar_select,
                name="zara_avatar_select",
                description=(
                    "Select and display an already-imported Zara avatar by "
                    "avatar_id, or by its display name."
                ),
                args_schema=SelectArgs,
            ),
        )

    # -- configuration ---------------------------------------------------------

    def _configure(self, configuration: Mapping[str, Any]) -> None:
        self._enabled = configuration.get("enabled", True)
        if not isinstance(self._enabled, bool):
            raise ValueError("enabled must be a boolean")
        if not self._enabled:
            return
        bind_address = str(configuration.get("bind_address", "127.0.0.1"))
        if bind_address != "127.0.0.1":
            raise ValueError("bind_address must be 127.0.0.1")
        self._port = _integer_setting(configuration, "port", DEFAULT_AVATAR_PORT, 0, 65535)
        self._avatar_directory = str(
            configuration.get("avatar_directory", DEFAULT_AVATAR_DIRECTORY)
        )
        if not self._avatar_directory.strip():
            raise ValueError("avatar_directory must be a non-empty path")
        self._request_size_limit = _integer_setting(
            configuration,
            "request_size_limit",
            DEFAULT_REQUEST_SIZE_LIMIT,
            1024,
            MAX_REQUEST_SIZE_LIMIT,
        )
        self._max_sse_clients = _integer_setting(
            configuration, "max_sse_clients", 4, 1, 16
        )
        self._command_timeout = _number_setting(
            configuration, "command_timeout", 5.0, 0.1, 60.0
        )
        self._renderer_startup_timeout = _number_setting(
            configuration, "renderer_startup_timeout", 10.0, 0.5, 60.0
        )
        self._renderer_request_timeout = _number_setting(
            configuration, "renderer_request_timeout", 5.0, 0.1, 60.0
        )
        self._renderer_load_timeout = _number_setting(
            configuration, "renderer_load_timeout", 20.0, 0.1, 120.0
        )
        self._max_renderer_restarts = _integer_setting(
            configuration, "max_renderer_restarts", DEFAULT_MAX_RENDERER_RESTARTS, 0, 10
        )
        self._restart_backoff = _number_setting(
            configuration, "restart_backoff", 1.0, 0.0, 30.0
        )
        self._idle_seed = _integer_setting(configuration, "idle_seed", 7, 0, 2**31)
        self._lipsync_mode = configuration.get("lipsync_mode", "analyzed")
        if self._lipsync_mode not in LIPSYNC_MODES:
            raise ValueError(
                "lipsync_mode must be one of: " + ", ".join(LIPSYNC_MODES)
            )
        self._lipsync_smoothing = _number_setting(
            configuration, "lipsync_smoothing", 0.35, 0.0, 1.0
        )
        self._lipsync_gain = _number_setting(
            configuration, "lipsync_gain", 1.0, 0.0, 10.0
        )
        self._lipsync_volume_influence = _number_setting(
            configuration, "lipsync_volume_influence", 1.0, 0.0, 2.0
        )
        self._renderer_command = _resolve_renderer_command(configuration)

    def _build_actor(self) -> AvatarActor:
        plugin = self

        def renderer_factory():
            command = plugin._renderer_command
            if not command:
                raise RendererUnavailable(
                    "no renderer command configured; set renderer_command in "
                    "[plugins.zara-avatar]"
                )
            return RendererHost(
                command=command,
                startup_timeout=plugin._renderer_startup_timeout,
                request_timeout=plugin._renderer_request_timeout,
            )

        def analyzer_factory():
            return VisemeAnalyzer(
                mode=self._lipsync_mode,
                smoothing=self._lipsync_smoothing,
                gain=self._lipsync_gain,
                volume_influence=self._lipsync_volume_influence,
            )

        return AvatarActor(
            library=self._library,
            renderer_factory=renderer_factory,
            analyzer_factory=analyzer_factory,
            seed=self._idle_seed,
            restart_backoff=self._restart_backoff,
            max_restarts=self._max_renderer_restarts,
            renderer_load_timeout=self._renderer_load_timeout,
        )

    # -- client surface ----------------------------------------------------------

    def submit(self, command: AvatarCommand, timeout: Optional[float] = None):
        if self._actor is None:
            raise ActorUnavailable("avatar plugin is disabled or stopped")
        return self._actor.submit(
            command,
            timeout=self._command_timeout if timeout is None else timeout,
        )

    def status_document(self) -> dict:
        if self._actor is not None:
            avatar = self._actor.status()
        else:
            avatar = AvatarState().to_document()
            avatar["renderer"] = {"state": "disabled"}
        return {
            "name": self.metadata.name,
            "version": self.metadata.version,
            "apiVersion": self.metadata.api_version,
            "state": "stopping" if self.stopping else "running",
            "avatar": avatar,
            "capabilities": {
                "events": True,
                "import": True,
                "expression": True,
                "gesture": True,
                "lipsync": self._enabled,
                "renderer": self._enabled,
            },
        }

    @property
    def stopping(self) -> bool:
        return self._stopping.is_set()

    @property
    def request_size_limit(self) -> int:
        return self._request_size_limit

    @property
    def actor(self) -> Optional[AvatarActor]:
        return self._actor

    def server_address(self):
        if self._server is None:
            return None
        return self._server.server_address

    def renderer_process(self):
        if self._actor is None or self._actor._renderer is None:
            return None
        return self._actor._renderer.process

    # -- event plumbing ------------------------------------------------------------

    def add_event_client(self) -> Optional[queue.Queue]:
        with self._event_clients_lock:
            if self.stopping or len(self._event_clients) >= self._max_sse_clients:
                return None
            client: queue.Queue = queue.Queue(maxsize=128)
            self._event_clients.add(client)
            return client

    def remove_event_client(self, client: queue.Queue) -> None:
        with self._event_clients_lock:
            self._event_clients.discard(client)

    def _serve(self, worker_stop: threading.Event) -> None:
        if self._server is None:
            raise RuntimeError("HTTP server is not initialized")
        try:
            while not worker_stop.is_set() and not self.stopping:
                self._server.handle_request()
        finally:
            self._server.server_close()

    def _pump_events(self, worker_stop: threading.Event) -> None:
        while not worker_stop.is_set() and not self.stopping:
            did_work = False
            if self._subscription is not None:
                try:
                    envelope = self._subscription.get(timeout=0.1)
                except queue.Empty:
                    envelope = None
                except Exception:
                    envelope = None
                if envelope is not None and self._actor is not None:
                    data = _jsonable_data(envelope.event)
                    self._actor.handle_runtime_event(
                        _event_name(envelope.event), data
                    )
                    did_work = True
            if self._actor is not None:
                events = self._actor.drain_state_events()
                for event in events:
                    self._broadcast(event)
                did_work = did_work or bool(events)
            if not did_work:
                # Bounded idle sleep: never busy-spin the pump worker.
                time.sleep(0.05)

    def _broadcast(self, event: Mapping[str, Any]) -> None:
        with self._event_clients_lock:
            clients = tuple(self._event_clients)
        if not clients:
            return
        self._event_sequence += 1
        payload = json.dumps(event, separators=(",", ":"))
        item = (self._event_sequence, payload)
        for client in clients:
            try:
                client.put_nowait(item)
                continue
            except queue.Full:
                pass
            try:
                client.get_nowait()
            except queue.Empty:
                pass
            try:
                client.put_nowait(item)
            except queue.Full:
                pass


def _jsonable_data(event: object) -> Optional[Mapping[str, Any]]:
    if dataclasses.is_dataclass(event):
        try:
            return dataclasses.asdict(event)
        except TypeError:
            return None
    return None


def _integer_setting(
    configuration: Mapping[str, Any],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    value = configuration.get(name, default)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return value


def _number_setting(
    configuration: Mapping[str, Any],
    name: str,
    default: float,
    minimum: float,
    maximum: float,
) -> float:
    value = configuration.get(name, default)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be between {minimum} and {maximum}")
    return number


def create_plugin() -> ZaraAvatarPlugin:
    return ZaraAvatarPlugin()


__all__ = [
    "AVATAR_PLUGIN_VERSION",
    "AvatarActor",
    "AvatarLibrary",
    "AvatarProtocolError",
    "AvatarRendererUnavailable",
    "AvatarState",
    "InvalidVrmError",
    "ZARA_AVATAR",
    "ZaraAvatarPlugin",
    "RendererHost",
    "VisemeAnalyzer",
    "create_plugin",
]
