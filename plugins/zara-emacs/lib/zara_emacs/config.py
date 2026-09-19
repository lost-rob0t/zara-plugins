"""Configuration for zara-emacs."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Mapping


class EmacsConfigError(ValueError):
    pass


WORKFLOW_OPERATIONS = frozenset(
    {
        "open_scratch",
        "open_file",
        "open_buffer",
        "open_daily",
        "open_magit",
        "open_dashboard",
        "open_zara_chat",
    }
)
_FIXED_WORKFLOW_OPERATIONS = frozenset(
    {"open_scratch", "open_dashboard", "open_zara_chat"}
)
_WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


@dataclass(frozen=True)
class EmacsWorkflowStep:
    operation: str
    argument: str | None = None


@dataclass(frozen=True)
class EmacsConfig:
    emacsclient: str = "emacsclient"
    server_name: str = "server"
    timeout_seconds: float = 10.0
    projects: Mapping[str, str] = field(default_factory=dict)
    workflows: Mapping[str, tuple[EmacsWorkflowStep, ...]] = field(default_factory=dict)

    @classmethod
    def load(cls, mapping: Mapping[str, Any] | None) -> "EmacsConfig":
        source = dict(mapping or {})
        emacsclient = source.get("emacsclient", "emacsclient")
        server_name = source.get("server_name", "server")
        timeout_seconds = source.get("timeout_seconds", 10.0)
        raw_projects = source.get("projects", {})
        raw_workflows = source.get("workflows", {})

        if not isinstance(emacsclient, str):
            raise EmacsConfigError("emacsclient must be a string")
        if not isinstance(server_name, str):
            raise EmacsConfigError("server_name must be a string")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
        ):
            raise EmacsConfigError("timeout_seconds must be a finite number")
        if not isinstance(raw_projects, Mapping):
            raise EmacsConfigError("projects must be an alias-to-path mapping")
        if not isinstance(raw_workflows, Mapping):
            raise EmacsConfigError("workflows must be a workflow-to-steps mapping")

        projects: dict[str, str] = {}
        for alias, path in raw_projects.items():
            if not isinstance(alias, str) or not isinstance(path, str):
                raise EmacsConfigError("project aliases and paths must be strings")
            projects[alias] = path

        workflows: dict[str, tuple[EmacsWorkflowStep, ...]] = {}
        for workflow_id, raw_steps in raw_workflows.items():
            if not isinstance(workflow_id, str):
                raise EmacsConfigError("workflow ids must be strings")
            if (
                not isinstance(raw_steps, (list, tuple))
                or isinstance(raw_steps, (str, bytes))
                or not raw_steps
                or len(raw_steps) > 32
            ):
                raise EmacsConfigError(
                    f"workflow {workflow_id!r} must contain 1 to 32 steps"
                )
            steps: list[EmacsWorkflowStep] = []
            for raw_step in raw_steps:
                if not isinstance(raw_step, Mapping):
                    raise EmacsConfigError("workflow steps must be mappings")
                unknown = set(raw_step) - {"operation", "argument"}
                if unknown:
                    raise EmacsConfigError(
                        f"workflow step contains unknown keys: {sorted(unknown)!r}"
                    )
                operation = raw_step.get("operation")
                argument = raw_step.get("argument")
                if not isinstance(operation, str):
                    raise EmacsConfigError("workflow operation must be a string")
                if argument is not None and not isinstance(argument, str):
                    raise EmacsConfigError("workflow argument must be a string or null")
                steps.append(EmacsWorkflowStep(operation=operation, argument=argument))
            workflows[workflow_id] = tuple(steps)

        config = cls(
            emacsclient=emacsclient,
            server_name=server_name,
            timeout_seconds=float(timeout_seconds),
            projects=projects,
            workflows=workflows,
        )
        config.validate()
        return config

    def validate(self) -> None:
        if (
            not isinstance(self.emacsclient, str)
            or not self.emacsclient
            or "/" in self.emacsclient
        ):
            raise EmacsConfigError(
                "emacsclient must be a command name, not a path or shell fragment"
            )
        if (
            not isinstance(self.server_name, str)
            or not self.server_name
            or len(self.server_name) > 128
            or any(ch.isspace() for ch in self.server_name)
        ):
            raise EmacsConfigError("server_name is invalid")
        if (
            isinstance(self.timeout_seconds, bool)
            or not isinstance(self.timeout_seconds, (int, float))
            or not math.isfinite(self.timeout_seconds)
            or not 0.1 <= self.timeout_seconds <= 60
        ):
            raise EmacsConfigError("timeout_seconds must be between 0.1 and 60")
        if not isinstance(self.projects, Mapping):
            raise EmacsConfigError("projects must be an alias-to-path mapping")
        for alias, path in self.projects.items():
            if not isinstance(alias, str) or not isinstance(path, str):
                raise EmacsConfigError("project aliases and paths must be strings")
            if not alias or len(alias) > 128:
                raise EmacsConfigError(
                    "project aliases must contain 1 to 128 characters"
                )
            if not Path(path).expanduser().is_absolute():
                raise EmacsConfigError(
                    f"project {alias!r} must map to an absolute path"
                )

        if not isinstance(self.workflows, Mapping):
            raise EmacsConfigError("workflows must be a workflow-to-steps mapping")
        for workflow_id, steps in self.workflows.items():
            if not isinstance(workflow_id, str) or not _WORKFLOW_ID_RE.fullmatch(
                workflow_id
            ):
                raise EmacsConfigError(f"invalid workflow id: {workflow_id!r}")
            if (
                not isinstance(steps, tuple)
                or not steps
                or len(steps) > 32
                or not all(isinstance(step, EmacsWorkflowStep) for step in steps)
            ):
                raise EmacsConfigError(
                    f"workflow {workflow_id!r} must contain 1 to 32 typed steps"
                )
            for step in steps:
                self._validate_workflow_step(workflow_id, step)

    def _validate_workflow_step(
        self, workflow_id: str, step: EmacsWorkflowStep
    ) -> None:
        if step.operation not in WORKFLOW_OPERATIONS:
            raise EmacsConfigError(
                f"unsupported workflow operation: {step.operation}"
            )

        argument = step.argument
        if argument is not None:
            if "\x00" in argument or len(argument) > 2048:
                raise EmacsConfigError(
                    f"workflow {workflow_id!r} has an invalid argument"
                )
            argument = argument.strip() or None

        if step.operation in _FIXED_WORKFLOW_OPERATIONS:
            if argument is not None:
                raise EmacsConfigError(
                    f"{step.operation} workflow steps do not accept arguments"
                )
            return

        if step.operation == "open_daily":
            if argument is None or argument == "today":
                return
            try:
                date.fromisoformat(argument)
            except ValueError as error:
                raise EmacsConfigError(
                    "open_daily workflow argument must be ISO YYYY-MM-DD or today"
                ) from error
            return

        if argument is None:
            raise EmacsConfigError(
                f"{step.operation} workflow steps require an argument"
            )

        if step.operation == "open_file" and not Path(argument).expanduser().is_absolute():
            raise EmacsConfigError(
                "open_file workflow arguments must be absolute paths"
            )
        if step.operation == "open_buffer" and len(argument) > 256:
            raise EmacsConfigError("open_buffer workflow arguments are too long")
        if step.operation == "open_magit" and argument not in self.projects:
            raise EmacsConfigError(
                f"workflow {workflow_id!r} uses unknown project alias: {argument}"
            )
