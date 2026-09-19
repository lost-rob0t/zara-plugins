"""Bounded named-workflow support for zara-emacs.

Workflow definitions are operator-owned configuration. Model/tool input selects only a
validated workflow id; it never supplies executable Elisp, shell, or ad-hoc steps.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Mapping

from .client import EmacsClient, EmacsError
from .config import EmacsConfig


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
_FIXED_OPERATIONS = frozenset({"open_scratch", "open_dashboard", "open_zara_chat"})
_WORKFLOW_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


class EmacsWorkflowConfigError(ValueError):
    pass


@dataclass(frozen=True)
class EmacsWorkflowStep:
    operation: str
    argument: str | None = None


def _validate_argument(
    workflow_id: str,
    operation: str,
    argument: str | None,
    projects: Mapping[str, str],
) -> str | None:
    if argument is not None:
        if not isinstance(argument, str):
            raise EmacsWorkflowConfigError("workflow argument must be a string or null")
        if "\x00" in argument or len(argument) > 2048:
            raise EmacsWorkflowConfigError(
                f"workflow {workflow_id!r} has an invalid argument"
            )
        argument = argument.strip() or None

    if operation in _FIXED_OPERATIONS:
        if argument is not None:
            raise EmacsWorkflowConfigError(
                f"{operation} workflow steps do not accept arguments"
            )
        return None

    if operation == "open_daily":
        if argument is None or argument == "today":
            return argument
        try:
            date.fromisoformat(argument)
        except ValueError as error:
            raise EmacsWorkflowConfigError(
                "open_daily workflow argument must be ISO YYYY-MM-DD or today"
            ) from error
        return argument

    if argument is None:
        raise EmacsWorkflowConfigError(f"{operation} workflow steps require an argument")

    if operation == "open_file" and not Path(argument).expanduser().is_absolute():
        raise EmacsWorkflowConfigError(
            "open_file workflow arguments must be absolute paths"
        )
    if operation == "open_buffer" and len(argument) > 256:
        raise EmacsWorkflowConfigError("open_buffer workflow arguments are too long")
    if operation == "open_magit" and argument not in projects:
        raise EmacsWorkflowConfigError(
            f"workflow {workflow_id!r} uses unknown project alias: {argument}"
        )
    return argument


def load_workflows(
    mapping: Mapping[str, Any] | None,
    *,
    projects: Mapping[str, str],
) -> dict[str, tuple[EmacsWorkflowStep, ...]]:
    """Load the closed, operator-owned workflow table from plugin configuration."""
    if mapping is not None and not isinstance(mapping, Mapping):
        raise EmacsWorkflowConfigError("plugin configuration must be a mapping")
    raw_workflows = dict(mapping or {}).get("workflows", {})
    if not isinstance(raw_workflows, Mapping):
        raise EmacsWorkflowConfigError("workflows must be a workflow-to-steps mapping")

    workflows: dict[str, tuple[EmacsWorkflowStep, ...]] = {}
    for workflow_id, raw_steps in raw_workflows.items():
        if not isinstance(workflow_id, str) or not _WORKFLOW_ID_RE.fullmatch(workflow_id):
            raise EmacsWorkflowConfigError(f"invalid workflow id: {workflow_id!r}")
        if (
            not isinstance(raw_steps, (list, tuple))
            or isinstance(raw_steps, (str, bytes))
            or not raw_steps
            or len(raw_steps) > 32
        ):
            raise EmacsWorkflowConfigError(
                f"workflow {workflow_id!r} must contain 1 to 32 steps"
            )

        steps: list[EmacsWorkflowStep] = []
        for raw_step in raw_steps:
            if not isinstance(raw_step, Mapping):
                raise EmacsWorkflowConfigError("workflow steps must be mappings")
            unknown = set(raw_step) - {"operation", "argument"}
            if unknown:
                raise EmacsWorkflowConfigError(
                    f"workflow step contains unknown keys: {sorted(unknown)!r}"
                )
            operation = raw_step.get("operation")
            if not isinstance(operation, str):
                raise EmacsWorkflowConfigError("workflow operation must be a string")
            if operation not in WORKFLOW_OPERATIONS:
                raise EmacsWorkflowConfigError(
                    f"unsupported workflow operation: {operation}"
                )
            argument = _validate_argument(
                workflow_id,
                operation,
                raw_step.get("argument"),
                projects,
            )
            steps.append(EmacsWorkflowStep(operation=operation, argument=argument))
        workflows[workflow_id] = tuple(steps)
    return workflows


class WorkflowEmacsClient(EmacsClient):
    """Emacs client with fixed editor commands and validated named workflows."""

    def __init__(
        self,
        config: EmacsConfig,
        *,
        workflows: Mapping[str, tuple[EmacsWorkflowStep, ...]],
        runner=None,
    ) -> None:
        super().__init__(config, runner=runner)
        self.workflows = dict(workflows)

    def open_dashboard(self) -> dict:
        expression = (
            "(progn (require 'ai-dashboard nil t) "
            "(unless (fboundp 'ai/dashboard) (error \"ai-dashboard unavailable\")) "
            "(ai/dashboard) t)"
        )
        self._eval(expression)
        return {"operation": "open_dashboard", "acknowledged": True}

    def open_zara_chat(self) -> dict:
        expression = (
            "(progn (require 'zara nil t) "
            "(unless (fboundp 'zara-chat) (error \"zara Emacs client unavailable\")) "
            "(zara-chat) t)"
        )
        self._eval(expression)
        return {"operation": "open_zara_chat", "acknowledged": True}

    def _run_workflow_step(self, step: EmacsWorkflowStep) -> dict:
        argument = step.argument
        if step.operation == "open_scratch":
            return self.open_scratch()
        if step.operation == "open_file":
            return self.open_file(str(argument))
        if step.operation == "open_buffer":
            return self.open_buffer(str(argument))
        if step.operation == "open_daily":
            return self.open_daily(argument or "today")
        if step.operation == "open_magit":
            return self.open_magit(str(argument))
        if step.operation == "open_dashboard":
            return self.open_dashboard()
        if step.operation == "open_zara_chat":
            return self.open_zara_chat()
        raise EmacsError(f"unsupported configured workflow operation: {step.operation}")

    def run_workflow(self, workflow_id: str) -> dict:
        if workflow_id not in self.workflows:
            raise EmacsError(f"unknown workflow: {workflow_id}")
        results: list[dict] = []
        for index, step in enumerate(self.workflows[workflow_id], start=1):
            try:
                results.append(self._run_workflow_step(step))
            except EmacsError as error:
                raise EmacsError(
                    f"workflow {workflow_id!r} failed at step {index} "
                    f"({step.operation}): {error}"
                ) from error
        return {
            "operation": "run_workflow",
            "workflow_id": workflow_id,
            "steps": results,
            "acknowledged": True,
        }
