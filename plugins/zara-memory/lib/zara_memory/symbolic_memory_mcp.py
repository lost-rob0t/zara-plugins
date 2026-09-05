from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Callable


class SymbolicMemoryMCPError(RuntimeError):
    pass


Runner = Callable[..., subprocess.CompletedProcess[str]]
SUPPORTED_SCOPES = frozenset({"project", "session", "global"})
SUPPORTED_KINDS = frozenset({"auto", "text", "fact", "episode", "preference", "procedure"})
SUPPORTED_RETENTION = frozenset({"long_term", "short_term", "session", "durable"})
PROTOCOL_VERSION = "2026-07-28"


class SymbolicMemoryMCP:
    def __init__(
        self,
        *,
        executable: str,
        database: Path,
        principal: str,
        session_id: str,
        capabilities: tuple[str, ...],
        project_remote: str | None = None,
        source_class: str = "model_inferred",
        timeout_seconds: float = 5.0,
        runner: Runner | None = None,
    ) -> None:
        for name, value in (
            ("executable", executable),
            ("principal", principal),
            ("session_id", session_id),
            ("source_class", source_class),
        ):
            if not isinstance(value, str) or not value:
                raise ValueError(f"{name} must be a non-empty string")
        if not capabilities or any(not isinstance(capability, str) or not capability for capability in capabilities):
            raise ValueError("capabilities must contain non-empty strings")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.executable = executable
        self.database = Path(database).expanduser()
        self.principal = principal
        self.session_id = session_id
        self.project_remote = project_remote
        self.source_class = source_class
        self.capabilities = tuple(capabilities)
        self.timeout_seconds = timeout_seconds
        self._runner = runner or subprocess.run
        self._request_id = 0

    def remember(
        self,
        text: str,
        *,
        scope: str = "project",
        retention: str = "long_term",
        kind: str = "text",
    ) -> dict[str, object]:
        if not isinstance(text, str) or not text:
            raise SymbolicMemoryMCPError("memory text must be non-empty")
        if scope not in SUPPORTED_SCOPES:
            raise SymbolicMemoryMCPError(f"unsupported symbolic-memory scope: {scope}")
        if retention not in SUPPORTED_RETENTION:
            raise SymbolicMemoryMCPError(f"unsupported symbolic-memory retention: {retention}")
        if kind not in SUPPORTED_KINDS:
            raise SymbolicMemoryMCPError(f"unsupported symbolic-memory kind: {kind}")
        return self._call(
            "memory_remember",
            {"memory": text, "scope": scope, "retention": retention, "kind": kind},
        )

    def get(self, memory_id: str) -> dict[str, object]:
        if not isinstance(memory_id, str) or not memory_id:
            raise SymbolicMemoryMCPError("memory id must be non-empty")
        return self._call("memory_get", {"id": memory_id})

    def _call(self, tool_name: str, arguments: dict[str, object]) -> dict[str, object]:
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": PROTOCOL_VERSION,
                    "io.modelcontextprotocol/clientInfo": {"name": "zara-memory", "version": "0.1.0"},
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        }
        env = os.environ.copy()
        env.update(
            {
                "SYMBOLIC_MEMORY_DB": str(self.database),
                "SYMBOLIC_MEMORY_PRINCIPAL": self.principal,
                "SYMBOLIC_MEMORY_SESSION_ID": self.session_id,
                "SYMBOLIC_MEMORY_SOURCE_CLASS": self.source_class,
                "SYMBOLIC_MEMORY_CAPABILITIES": ",".join(self.capabilities),
            }
        )
        if self.project_remote:
            env["SYMBOLIC_MEMORY_PROJECT_REMOTE"] = self.project_remote
        else:
            env.pop("SYMBOLIC_MEMORY_PROJECT_REMOTE", None)
        try:
            completed = self._runner(
                [self.executable],
                input=json.dumps(request) + "\n",
                check=True,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
                shell=False,
                env=env,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            raise SymbolicMemoryMCPError("symbolic-memory MCP invocation failed") from exc
        response = self._parse_response(completed.stdout)
        result = response.get("result")
        if not isinstance(result, dict):
            error = response.get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                raise SymbolicMemoryMCPError(error["message"])
            raise SymbolicMemoryMCPError("symbolic-memory MCP returned no result")
        if result.get("isError") is True:
            content = result.get("content", [])
            message = "symbolic-memory MCP tool failed"
            if isinstance(content, list) and content and isinstance(content[0], dict):
                text = content[0].get("text")
                if isinstance(text, str) and text:
                    message = text
            raise SymbolicMemoryMCPError(message)
        structured = result.get("structuredContent")
        if not isinstance(structured, dict):
            raise SymbolicMemoryMCPError("symbolic-memory MCP returned no structured evidence")
        return dict(structured)

    @staticmethod
    def _parse_response(stdout: str) -> dict[str, object]:
        lines = [line for line in stdout.splitlines() if line.strip()]
        if not lines:
            raise SymbolicMemoryMCPError("symbolic-memory MCP returned empty output")
        try:
            response = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise SymbolicMemoryMCPError("symbolic-memory MCP returned invalid JSON") from exc
        if not isinstance(response, dict):
            raise SymbolicMemoryMCPError("symbolic-memory MCP returned invalid response")
        return response
