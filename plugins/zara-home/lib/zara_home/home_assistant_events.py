from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from .home_assistant import HomeAssistantAdapter, HomeAssistantError
from .home_assistant_transport import HomeAssistantHTTPTransport


class HomeAssistantEventError(RuntimeError):
    pass


class HomeAssistantEventStream:
    """Bounded Home Assistant state_changed observer.

    The stream is observation-only. Mutation verification remains the responsibility
    of HomeService's independent REST read-back path.
    """

    def __init__(
        self,
        base_url: str,
        access_token: str,
        *,
        connect: Callable[[str], Any],
        reconcile: Callable[[], list[dict[str, Any]]],
        max_frame_bytes: int = 1024 * 1024,
        io_timeout_seconds: float = 10.0,
        reconnect_backoff: tuple[float, ...] = (1.0, 2.0, 5.0, 10.0),
        wait: Callable[[float], bool] | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise HomeAssistantEventError("invalid-base-url")
        if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
            raise HomeAssistantEventError("invalid-base-url")
        if parsed.path not in {"", "/"}:
            raise HomeAssistantEventError("invalid-base-url")
        if not HomeAssistantHTTPTransport._valid_bearer_token(access_token):
            raise HomeAssistantEventError("invalid-access-token")
        if not isinstance(max_frame_bytes, int) or max_frame_bytes < 256 or max_frame_bytes > 4 * 1024 * 1024:
            raise HomeAssistantEventError("invalid-frame-limit")
        if not isinstance(io_timeout_seconds, (int, float)) or isinstance(io_timeout_seconds, bool) or io_timeout_seconds <= 0 or io_timeout_seconds > 60:
            raise HomeAssistantEventError("invalid-io-timeout")
        if (
            not isinstance(reconnect_backoff, tuple)
            or not reconnect_backoff
            or len(reconnect_backoff) > 8
            or any(
                not isinstance(delay, (int, float))
                or isinstance(delay, bool)
                or delay <= 0
                or delay > 60
                for delay in reconnect_backoff
            )
        ):
            raise HomeAssistantEventError("invalid-reconnect-backoff")

        scheme = "wss" if parsed.scheme == "https" else "ws"
        self.websocket_url = urlunsplit((scheme, parsed.netloc, "/api/websocket", "", ""))
        self._access_token = access_token
        self._connect = connect
        self._reconcile = reconcile
        self._max_frame_bytes = max_frame_bytes
        self._io_timeout_seconds = float(io_timeout_seconds)
        self._reconnect_backoff = tuple(float(delay) for delay in reconnect_backoff)
        self._stop_event = threading.Event()
        self._wait = wait or self._stop_event.wait
        self._socket = None
        self._subscription_id: int | None = None
        self._next_id = 1
        self._observations: dict[str, dict[str, Any]] = {}
        self._timestamps: dict[str, datetime] = {}
        self._stopped = False
        self._thread: threading.Thread | None = None
        self.fresh = False

    @classmethod
    def from_transport(cls, transport: HomeAssistantHTTPTransport) -> "HomeAssistantEventStream":
        def connect(url: str):
            try:
                import websocket
            except ImportError:
                raise HomeAssistantEventError("websocket-client-unavailable") from None
            try:
                return websocket.create_connection(
                    url,
                    timeout=transport.timeout,
                    enable_multithread=True,
                )
            except Exception:
                raise HomeAssistantEventError("provider-unavailable") from None

        return cls(
            transport.base_url,
            transport._access_token,
            connect=connect,
            reconcile=lambda: transport.request("GET", "/api/states"),
            io_timeout_seconds=transport.timeout,
        )

    def start(self) -> None:
        if self._stopped:
            raise HomeAssistantEventError("stopped")
        if self._thread is not None and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self.run_forever,
            name="zara-home-ha-events",
            daemon=True,
        )
        self._thread.start()

    def run_forever(self) -> None:
        backoff_index = 0
        while not self._stopped:
            try:
                self.connect_once()
                while not self._stopped:
                    self.poll_once()
                    if self.fresh:
                        backoff_index = 0
            except HomeAssistantEventError:
                self.mark_disconnected()
                if self._stopped:
                    break
                delay = self._reconnect_backoff[min(backoff_index, len(self._reconnect_backoff) - 1)]
                backoff_index = min(backoff_index + 1, len(self._reconnect_backoff) - 1)
                if self._wait(delay):
                    break
        self.mark_disconnected()

    def connect_once(self) -> None:
        if self._stopped:
            raise HomeAssistantEventError("stopped")
        self.fresh = False
        self._subscription_id = None
        try:
            sock = self._connect(self.websocket_url)
            settimeout = getattr(sock, "settimeout", None)
            if callable(settimeout):
                settimeout(self._io_timeout_seconds)
            first = self._read_frame(sock)
            if first.get("type") != "auth_required":
                raise HomeAssistantEventError("invalid-auth-phase")
            sock.send(json.dumps({"type": "auth", "access_token": self._access_token}))
            auth = self._read_frame(sock)
            if auth.get("type") == "auth_invalid":
                raise HomeAssistantEventError("reauth-required")
            if auth.get("type") != "auth_ok":
                raise HomeAssistantEventError("invalid-auth-phase")

            subscription_id = self._next_id
            self._next_id += 1
            sock.send(json.dumps({"id": subscription_id, "type": "subscribe_events", "event_type": "state_changed"}))
            self._socket = sock
            self._subscription_id = subscription_id
        except HomeAssistantEventError:
            self._close_socket(locals().get("sock"))
            raise
        except Exception:
            self._close_socket(locals().get("sock"))
            raise HomeAssistantEventError("provider-unavailable") from None

    def poll_once(self) -> None:
        if self._stopped:
            raise HomeAssistantEventError("stopped")
        if self._socket is None or self._subscription_id is None:
            raise HomeAssistantEventError("not-connected")
        try:
            frame = self._read_frame(self._socket)
            frame_type = frame.get("type")
            frame_id = frame.get("id")
            if not isinstance(frame_id, int) or isinstance(frame_id, bool):
                return
            if frame_id != self._subscription_id:
                return
            if frame_type == "result":
                if frame.get("success") is not True:
                    self.fresh = False
                    raise HomeAssistantEventError("subscription-failed")
                self._reconcile_now()
                self.fresh = True
                return
            if frame_type != "event" or not self.fresh:
                return
            self._apply_event(frame)
        except HomeAssistantEventError:
            self.fresh = False
            raise
        except Exception:
            self.mark_disconnected()
            raise HomeAssistantEventError("provider-unavailable") from None

    def mark_disconnected(self) -> None:
        self.fresh = False
        self._subscription_id = None
        sock = self._socket
        self._socket = None
        self._close_socket(sock)

    def stop(self) -> None:
        self._stopped = True
        self._stop_event.set()
        self.mark_disconnected()

    def observation(self, entity_id: str) -> dict[str, Any] | None:
        value = self._observations.get(entity_id)
        return None if value is None else dict(value)

    def observations(self) -> dict[str, dict[str, Any]]:
        return {entity_id: dict(value) for entity_id, value in self._observations.items()}

    def _read_frame(self, sock: Any) -> dict[str, Any]:
        try:
            raw = sock.recv()
        except Exception:
            raise HomeAssistantEventError("provider-unavailable") from None
        if not isinstance(raw, str):
            raise HomeAssistantEventError("invalid-frame")
        if len(raw.encode("utf-8")) > self._max_frame_bytes:
            raise HomeAssistantEventError("frame-too-large")
        try:
            frame = json.loads(raw)
        except json.JSONDecodeError:
            raise HomeAssistantEventError("invalid-json") from None
        if not isinstance(frame, dict):
            raise HomeAssistantEventError("invalid-frame")
        return frame

    def _reconcile_now(self) -> None:
        try:
            states = self._reconcile()
        except Exception:
            raise HomeAssistantEventError("reconcile-failed") from None
        if not isinstance(states, list):
            raise HomeAssistantEventError("reconcile-failed")

        present: set[str] = set()
        for state in states:
            if not isinstance(state, dict):
                continue
            entity_id = state.get("entity_id")
            if isinstance(entity_id, str) and self._supported_entity(entity_id):
                present.add(entity_id)
            self._apply_state(state)

        for entity_id in tuple(self._observations):
            if self._supported_entity(entity_id) and entity_id not in present:
                self._observations.pop(entity_id, None)

    def _apply_event(self, frame: dict[str, Any]) -> None:
        event = frame.get("event")
        if not isinstance(event, dict) or event.get("event_type") != "state_changed":
            return
        data = event.get("data")
        if not isinstance(data, dict):
            return
        entity_id = data.get("entity_id")
        new_state = data.get("new_state")
        if not isinstance(entity_id, str) or not self._supported_entity(entity_id):
            return
        if new_state is None:
            self._apply_removal(entity_id, event.get("time_fired"))
            return
        if not isinstance(new_state, dict) or new_state.get("entity_id") != entity_id:
            return
        self._apply_state(new_state)

    def _apply_removal(self, entity_id: str, time_fired: Any) -> None:
        removed_at = self._timestamp(time_fired)
        if removed_at is None:
            return
        current = self._timestamps.get(entity_id)
        if current is not None and removed_at <= current:
            return
        self._observations.pop(entity_id, None)
        self._timestamps[entity_id] = removed_at

    def _apply_state(self, raw: dict[str, Any]) -> None:
        entity_id = raw.get("entity_id")
        if not isinstance(entity_id, str) or not self._supported_entity(entity_id):
            return
        updated = self._timestamp(raw.get("last_updated"))
        if updated is None:
            return
        current = self._timestamps.get(entity_id)
        if current is not None and updated <= current:
            return
        try:
            normalized = HomeAssistantAdapter._normalize(raw)
        except HomeAssistantError:
            return
        observation = dict(normalized)
        observation["last_updated"] = raw["last_updated"]
        if isinstance(raw.get("last_changed"), str):
            observation["last_changed"] = raw["last_changed"]
        self._observations[entity_id] = observation
        self._timestamps[entity_id] = updated

    @staticmethod
    def _supported_entity(entity_id: str) -> bool:
        try:
            domain = HomeAssistantAdapter._domain(entity_id)
        except HomeAssistantError:
            return False
        return domain in HomeAssistantAdapter._DEVICE_DOMAINS

    @staticmethod
    def _timestamp(value: Any) -> datetime | None:
        if not isinstance(value, str) or not value:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return None
        return parsed

    @staticmethod
    def _close_socket(sock: Any) -> None:
        if sock is None:
            return
        try:
            sock.close()
        except Exception:
            pass
