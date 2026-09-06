from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import CommandPolicy, ShellError, ShellRunner


PLUGIN_VERSION = "0.1.0"
APPROVAL_METADATA = {"zara_requires_approval": True}


class ZaraShellPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-shell",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Approval-gated constrained argv execution",
    )

    def __init__(self) -> None:
        self.runner: ShellRunner | None = None

    def start(self, runtime) -> None:
        section = self._section(runtime.configuration)
        programs = self._string_list(section.get("allowed_programs", []), "allowed_programs")
        roots = self._string_list(section.get("allowed_roots", []), "allowed_roots")
        environment = self._string_list(section.get("allowed_environment", []), "allowed_environment")
        if not programs or not roots:
            self.runner = None
            return
        policy = CommandPolicy(
            allowed_programs=set(programs),
            allowed_roots=tuple(Path(value).expanduser() for value in roots),
            allowed_environment=set(environment),
            max_runtime_seconds=float(section.get("max_runtime_seconds", 10.0)),
            max_output_bytes=int(section.get("max_output_bytes", 65536)),
            max_input_bytes=int(section.get("max_input_bytes", 65536)),
            max_environment_bytes=int(section.get("max_environment_bytes", 4096)),
        )
        self.runner = ShellRunner(policy)

    def stop(self) -> None:
        self.runner = None

    def status(self) -> str:
        if self.runner is None:
            return self._json({"status": "unavailable", "reason": "shell-policy-not-configured"})
        policy = self.runner.policy
        return self._json(
            {
                "status": "ready",
                "allowed_program_count": len(policy.allowed_programs),
                "allowed_root_count": len(policy.allowed_roots),
                "allowed_environment_count": len(policy.allowed_environment),
                "max_runtime_seconds": policy.max_runtime_seconds,
                "max_output_bytes": policy.max_output_bytes,
                "max_input_bytes": policy.max_input_bytes,
                "max_environment_bytes": policy.max_environment_bytes,
            }
        )

    def run(
        self,
        argv: list[str],
        cwd: str,
        env: dict[str, str] | None = None,
        stdin: str = "",
    ) -> str:
        if self.runner is None:
            raise ShellError("shell policy is not configured")
        return self._json(
            self.runner.run(
                argv,
                cwd=Path(cwd).expanduser(),
                env=env,
                stdin=stdin,
            )
        )

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.status,
                name="shell.status",
                description="Report whether the constrained shell policy is configured and its public bounds.",
            ),
            StructuredTool.from_function(
                func=self.run,
                name="shell.run",
                description="Run one explicitly allowlisted argv command inside a configured root with bounded input, output, runtime, and operator-allowlisted environment keys. Never invokes a shell.",
                metadata=APPROVAL_METADATA,
            ),
        )

    @staticmethod
    def _section(configuration: object) -> Mapping[str, object]:
        if not isinstance(configuration, Mapping):
            return {}
        plugins = configuration.get("plugins")
        if not isinstance(plugins, Mapping):
            return {}
        section = plugins.get("zara-shell")
        if section is None:
            return {}
        if not isinstance(section, Mapping):
            raise ShellError("zara-shell configuration must be a mapping")
        return section

    @staticmethod
    def _string_list(value: object, name: str) -> tuple[str, ...]:
        if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
            raise ShellError(f"zara-shell {name} must be a list")
        if any(not isinstance(item, str) for item in value):
            raise ShellError(f"zara-shell {name} must contain strings")
        normalized = tuple(item.strip() for item in value)
        if any(not item for item in normalized):
            raise ShellError(f"zara-shell {name} contains an empty value")
        return normalized

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)


def create_plugin():
    return ZaraShellPlugin()
