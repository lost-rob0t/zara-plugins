"""Client for the Local Recall zara-visual-context-v1 IPC protocol."""

from __future__ import annotations

import json
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from .paths import MAX_RESPONSE_BYTES, RuntimePaths

PROTOCOL_VERSION = "zara-visual-context-v1"
MAX_RECORDS = 8
SendFrames = Callable[[list[bytes], float], bytes]


@dataclass(frozen=True, slots=True, repr=False)
class VisualContextAnswer:
    outcome: str
    explanation: str
    record_count: int
    provider_class: str | None
    reason_code: str | None

    def __repr__(self) -> str:
        return (
            f"VisualContextAnswer(outcome={self.outcome!r}, "
            f"record_count={self.record_count}, content=redacted)"
        )


def new_request_id() -> str:
    return secrets.token_hex(8)


def build_request(
    *,
    selector: str,
    maximum_records: int,
    request_id: str,
    now: datetime | None = None,
) -> list[bytes]:
    if selector not in {"current", "recent"}:
        raise RuntimeError("invalid-selector")
    if not 1 <= maximum_records <= MAX_RECORDS:
        raise RuntimeError("invalid-record-budget")
    if not request_id or len(request_id) > 128:
        raise RuntimeError("invalid-request-id")
    deadline = (now or datetime.now(UTC)) + timedelta(seconds=8)
    routing = {
        "protocol_version": "ipc-v1",
        "visual_context_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "remote_authorization": "absent",
    }
    payload = {
        "deadline": deadline.isoformat(),
        "end": None,
        "maximum_records": maximum_records,
        "selector": selector,
        "start": None,
    }
    return [
        json.dumps(routing, sort_keys=True, separators=(",", ":")).encode("utf-8"),
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8"),
    ]


def parse_response(raw: bytes, *, request_id: str) -> VisualContextAnswer:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("visual-response-too-large")
    document: Any = json.loads(raw.decode("utf-8"))
    if not isinstance(document, dict):
        raise RuntimeError("visual-response-invalid")
    values = dict[str, Any](document)
    if values.get("protocol_version") != PROTOCOL_VERSION:
        raise RuntimeError("visual-version-mismatch")
    if values.get("request_id") != request_id:
        raise RuntimeError("visual-response-mismatch")
    outcome = values.get("outcome")
    if outcome not in {"explained", "denied", "unavailable"}:
        raise RuntimeError("visual-response-invalid")
    explanation = values.get("explanation")
    record_count = values.get("record_count")
    provider_class = values.get("provider_class")
    reason_code = values.get("reason_code")
    return VisualContextAnswer(
        outcome=str(outcome),
        explanation=explanation if isinstance(explanation, str) else "",
        record_count=record_count if isinstance(record_count, int) else 0,
        provider_class=provider_class if isinstance(provider_class, str) else None,
        reason_code=reason_code if isinstance(reason_code, str) else None,
    )


def _authenticated_transport(
    paths: RuntimePaths,
) -> SendFrames:
    def send(frames: list[bytes], timeout_seconds: float) -> bytes:
        import zmq

        token = paths.token_path.read_bytes()
        if len(token) != MAX_TOKEN_LENGTH:
            raise RuntimeError("visual-token-invalid")
        paths.validate()
        context = zmq.Context()
        socket = context.socket(zmq.DEALER)
        socket.setsockopt(zmq.LINGER, 0)
        socket.setsockopt(zmq.RCVTIMEO, int(timeout_seconds * 1000))
        socket.setsockopt(zmq.SNDTIMEO, int(timeout_seconds * 1000))
        try:
            socket.connect(f"ipc://{paths.socket_path}")
            socket.send_multipart([*frames[:1], token, *frames[1:]])
            reply = socket.recv_multipart()
        finally:
            socket.close(linger=0)
            context.term()
        if len(reply) != 1:
            raise RuntimeError("visual-response-invalid")
        return reply[0]

    return send


MAX_TOKEN_LENGTH = 32


def explain_screen(
    *,
    selector: str,
    maximum_records: int,
    timeout_seconds: float,
    paths: RuntimePaths | None = None,
    send: SendFrames | None = None,
) -> VisualContextAnswer:
    if send is None:
        resolved_paths = paths or RuntimePaths.from_environment()
        resolved_send = _authenticated_transport(resolved_paths)
    else:
        resolved_send = send
    request_id = new_request_id()
    frames = build_request(
        selector=selector,
        maximum_records=maximum_records,
        request_id=request_id,
    )
    raw = resolved_send(frames, timeout_seconds)
    return parse_response(raw, request_id=request_id)
