from __future__ import annotations

import json
import math
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import PiError, PiPolicy, TmuxBridge


PLUGIN_VERSION = "0.1.0"
APPROVAL_METADATA = {"zara_requires_approval": True}


class ZaraPiPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-pi",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Approval-backed Pi coding-agent Bash and owned tmux sessions",
    )

    def __init__(self) -> None:
        self.bridge: TmuxBridge | None = None
        self.policy: PiPolicy | None = None
        self._configured = False
        self._pi_available = False
        self._tmux_available = False
        self._bash_available = False

    def start(self, runtime) -> None:
        section = self._section(runtime.configuration)
        roots = self._string_list(section.get("allowed_roots", []), "allowed_roots")
        self.bridge = None
        self.policy = None
        self._configured = bool(roots)
        self._pi_available = False
        self._tmux_available = False
        self._bash_available = False
        if not roots:
            return
        pi_requested = self._program(section.get("pi", "pi"), "pi")
        tmux_requested = self._program(section.get("tmux", "tmux"), "tmux")
        bash_requested = self._program(section.get("bash", "bash"), "bash")
        pi_program = shutil.which(pi_requested)
        tmux_program = shutil.which(tmux_requested)
        bash_program = shutil.which(bash_requested)
        self._pi_available = pi_program is not None
        self._tmux_available = tmux_program is not None
        self._bash_available = bash_program is not None
        policy = PiPolicy(
            allowed_roots=tuple(Path(value).expanduser() for value in roots),
            pi_program=pi_program or pi_requested,
            tmux_program=tmux_program or tmux_requested,
            bash_program=bash_program or bash_requested,
            max_command_bytes=self._positive_int(
                section.get("max_command_bytes", 65536), "max_command_bytes"
            ),
            max_capture_bytes=self._positive_int(
                section.get("max_capture_bytes", 65536), "max_capture_bytes"
            ),
            max_tmux_lines=self._positive_int(
                section.get("max_tmux_lines", 2000), "max_tmux_lines"
            ),
            operation_timeout_seconds=self._finite_positive_number(
                section.get("operation_timeout_seconds", 5.0),
                "operation_timeout_seconds",
            ),
        )
        self.policy = policy
        if self._tmux_available and self._bash_available:
            self.bridge = TmuxBridge(policy)

    def stop(self) -> None:
        self.bridge = None
        self.policy = None
        self._configured = False
        self._pi_available = False
        self._tmux_available = False
        self._bash_available = False

    def status(self) -> str:
        if not self._configured or self.policy is None:
            return self._json({"status": "unavailable", "reason": "pi-policy-not-configured"})
        ready = self._pi_available and self._tmux_available and self._bash_available
        return self._json(
            {
                "status": "ready" if ready else "degraded",
                "pi_available": self._pi_available,
                "tmux_available": self._tmux_available,
                "bash_available": self._bash_available,
                "tmux_bridge_ready": self.bridge is not None,
                "allowed_root_count": len(self.policy.allowed_roots),
                "max_command_bytes": self.policy.max_command_bytes,
                "max_capture_bytes": self.policy.max_capture_bytes,
                "max_tmux_lines": self.policy.max_tmux_lines,
                "operation_timeout_seconds": self.policy.operation_timeout_seconds,
                "pi_rpc_mode": "planned",
                "pi_rpc_effect_adapter_ready": False,
            }
        )

    def bash(self, session_id: str, invocation_id: str, command: str, cwd: str) -> str:
        bridge = self._require_bridge()
        return self._json(
            bridge.bash(
                session_id=session_id,
                invocation_id=invocation_id,
                command=command,
                cwd=Path(cwd).expanduser(),
            )
        )

    def tmux_ensure(self, session_id: str, cwd: str) -> str:
        bridge = self._require_bridge()
        return self._json(bridge.ensure(session_id, Path(cwd).expanduser()))

    def tmux_capture(self, session_id: str, invocation_id: str | None = None) -> str:
        bridge = self._require_bridge()
        return self._json(bridge.capture(session_id, invocation_id=invocation_id))

    def tmux_interrupt(self, session_id: str, invocation_id: str) -> str:
        bridge = self._require_bridge()
        return self._json(bridge.interrupt(session_id, invocation_id))

    def tmux_close(self, session_id: str) -> str:
        bridge = self._require_bridge()
        return self._json(bridge.close(session_id))

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.status,
                name="pi.status",
                description="Report Pi, tmux, Bash, root-policy, and bridge readiness without exposing credentials or environment values.",
            ),
            StructuredTool.from_function(
                func=self.bash,
                name="pi.bash",
                description="Run one approval-gated Bash command inside a Zara-owned tmux session rooted in an operator-configured project tree. Returns an invocation identity; use pi.tmux.capture for bounded completion evidence.",
                metadata=APPROVAL_METADATA,
            ),
            StructuredTool.from_function(
                func=self.tmux_ensure,
                name="pi.tmux.ensure",
                description="Create or reuse one Zara-owned Bash tmux session beneath an allowed project root.",
                metadata=APPROVAL_METADATA,
            ),
            StructuredTool.from_function(
                func=self.tmux_capture,
                name="pi.tmux.capture",
                description="Capture bounded sanitized output from one Zara-owned tmux session and, when an invocation id is supplied, return marker-backed Bash completion evidence.",
                metadata=APPROVAL_METADATA,
            ),
            StructuredTool.from_function(
                func=self.tmux_interrupt,
                name="pi.tmux.interrupt",
                description="Send Ctrl-C only to the exact currently registered invocation in one Zara-owned tmux session. This reports that an interrupt was sent, not that termination is proven.",
                metadata=APPROVAL_METADATA,
            ),
            StructuredTool.from_function(
                func=self.tmux_close,
                name="pi.tmux.close",
                description="Close one exact Zara-owned tmux session. Non-Zara sessions are never adopted or killed.",
                metadata=APPROVAL_METADATA,
            ),
        )

    def _require_bridge(self) -> TmuxBridge:
        if self.bridge is None:
            raise PiError("Pi tmux bridge is not configured or tmux/Bash is unavailable")
        return self.bridge

    @staticmethod
    def _section(configuration: object) -> Mapping[str, object]:
        if not isinstance(configuration, Mapping):
            return {}
        plugins = configuration.get("plugins")
        if not isinstance(plugins, Mapping):
            return {}
        section = plugins.get("zara-pi")
        if section is None:
            return {}
        if not isinstance(section, Mapping):
            raise PiError("zara-pi configuration must be a mapping")
        return section

    @staticmethod
    def _string_list(value: object, name: str) -> tuple[str, ...]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise PiError(f"zara-pi {name} must be a list")
        if any(not isinstance(item, str) for item in value):
            raise PiError(f"zara-pi {name} must contain strings")
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise PiError(f"zara-pi {name} contains an empty value")
        return normalized

    @staticmethod
    def _program(value: object, name: str) -> str:
        if not isinstance(value, str) or not value.strip() or "\0" in value:
            raise PiError(f"zara-pi {name} must be a non-empty program name or path")
        return value.strip()

    @staticmethod
    def _positive_int(value: object, name: str) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise PiError(f"zara-pi {name} must be a positive integer")
        return value

    @staticmethod
    def _finite_positive_number(value: object, name: str) -> float:
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value <= 0
        ):
            raise PiError(f"zara-pi {name} must be finite positive")
        return float(value)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)


def create_plugin():
    return ZaraPiPlugin()
