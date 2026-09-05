from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import PrologRLMBridge, RepositoryInspector


PLUGIN_VERSION = "0.1.0"


class ZaraCodingPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-coding",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Bounded repository evidence and Prolog-RLM coding harness preflight",
    )

    def __init__(self) -> None:
        self.inspector: RepositoryInspector | None = None
        self.prolog_rlm: PrologRLMBridge | None = None
        self.repository_reason = "not-started"

    def start(self, runtime) -> None:
        section = self._section(runtime.configuration)
        roots = self._string_list(section.get("allowed_roots", []), "allowed_roots")
        git_executable = section.get("git", "git")
        if not isinstance(git_executable, str) or not git_executable:
            raise ValueError("git must be a non-empty string")
        if not roots:
            self.inspector = None
            self.repository_reason = "allowed-roots-not-configured"
        elif shutil.which(git_executable) is None:
            self.inspector = None
            self.repository_reason = "git-executable-not-found"
        else:
            self.inspector = RepositoryInspector(tuple(Path(root) for root in roots), executable=git_executable)
            self.repository_reason = "ready"

        checkout = section.get("prolog_rlm_checkout")
        if checkout is not None and not isinstance(checkout, str):
            raise ValueError("prolog_rlm_checkout must be a string")
        executable = section.get("swipl", "swipl")
        if not isinstance(executable, str) or not executable:
            raise ValueError("swipl must be a non-empty string")
        self.prolog_rlm = PrologRLMBridge(Path(checkout), executable=executable) if checkout else None

    def stop(self) -> None:
        self.inspector = None
        self.prolog_rlm = None
        self.repository_reason = "stopped"

    def tools(self) -> Sequence[StructuredTool]:
        return (
            StructuredTool.from_function(
                func=self.status,
                name="coding.status",
                description="Report repository-boundary and Prolog-RLM readiness without mutating state.",
            ),
            StructuredTool.from_function(
                func=self.list_repositories,
                name="coding.repo.list",
                description="List bounded immediate Git repository roots under configured repository boundaries.",
            ),
            StructuredTool.from_function(
                func=self.repo_status,
                name="coding.repo.status",
                description="Return branch/head/dirty status for one allowed repository.",
            ),
            StructuredTool.from_function(
                func=self.inspect_repo,
                name="coding.repo.inspect",
                description="Return structured Git branch/head/dirty evidence for an allowed repository.",
            ),
            StructuredTool.from_function(
                func=self.git_diff,
                name="coding.git.diff",
                description="Return bounded structured working-tree diff statistics for an allowed repository.",
            ),
            StructuredTool.from_function(
                func=self.git_log,
                name="coding.git.log",
                description="Return bounded structured commit history for an allowed repository.",
            ),
            StructuredTool.from_function(
                func=self.git_branches,
                name="coding.git.branches",
                description="Return bounded structured local branch refs for an allowed repository.",
            ),
            StructuredTool.from_function(
                func=self.git_worktrees,
                name="coding.git.worktrees",
                description="Return bounded structured Git worktree inventory for an allowed repository.",
            ),
            StructuredTool.from_function(
                func=self.spec_catalog,
                name="coding.spec.catalog",
                description=(
                    "Return Prolog-RLM's canonical closed SPEC structural vocabulary and the assertion "
                    "kinds currently admitted by this bridge."
                ),
            ),
            StructuredTool.from_function(
                func=self.normalize_spec,
                name="coding.spec.normalize",
                description=(
                    "Normalize one closed declarative SPEC source through Prolog-RLM and return its "
                    "canonical outcome without planning or mutation."
                ),
            ),
        )

    def status(self) -> str:
        repository = (
            {"status": "ready"}
            if self.inspector is not None
            else {"status": "unavailable", "reason": self.repository_reason}
        )
        prolog_rlm = (
            self.prolog_rlm.status()
            if self.prolog_rlm is not None
            else {"status": "unavailable", "reason": "prolog-rlm-checkout-not-configured"}
        )
        state = "ready" if repository["status"] == "ready" and prolog_rlm["status"] == "ready" else "degraded"
        return json.dumps({"status": state, "repository": repository, "prolog_rlm": prolog_rlm}, sort_keys=True)

    def list_repositories(self, limit: int = 50) -> str:
        inspector = self._require_inspector()
        return json.dumps(inspector.list_repositories(limit=limit), sort_keys=True)

    def repo_status(self, path: str) -> str:
        return self.inspect_repo(path)

    def inspect_repo(self, path: str) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        return json.dumps(inspector.inspect(Path(path)), sort_keys=True)

    def git_diff(self, path: str, max_files: int = 50) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        return json.dumps(inspector.diff(Path(path), max_files=max_files), sort_keys=True)

    def git_log(self, path: str, limit: int = 20) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        return json.dumps(inspector.log(Path(path), limit=limit), sort_keys=True)

    def git_branches(self, path: str, limit: int = 50) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        return json.dumps(inspector.branches(Path(path), limit=limit), sort_keys=True)

    def git_worktrees(self, path: str, limit: int = 50) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        return json.dumps(inspector.worktrees(Path(path), limit=limit), sort_keys=True)

    def spec_catalog(self) -> str:
        bridge = self._require_prolog_rlm()
        return json.dumps(bridge.spec_catalog(), sort_keys=True)

    def normalize_spec(self, source: str) -> str:
        bridge = self._require_prolog_rlm()
        return json.dumps(bridge.normalize_spec(source), sort_keys=True)

    def _require_inspector(self) -> RepositoryInspector:
        if self.inspector is None:
            raise RuntimeError(f"zara-coding repository inspection unavailable: {self.repository_reason}")
        return self.inspector

    def _require_prolog_rlm(self) -> PrologRLMBridge:
        if self.prolog_rlm is None:
            raise RuntimeError("zara-coding Prolog-RLM checkout is not configured")
        return self.prolog_rlm

    @staticmethod
    def _section(configuration) -> Mapping[str, object]:
        if not isinstance(configuration, Mapping):
            return {}
        plugins = configuration.get("plugins", {})
        if not isinstance(plugins, Mapping):
            return {}
        section = plugins.get("zara-coding", {})
        if not isinstance(section, Mapping):
            raise ValueError("plugins.zara-coding must be a table")
        return section

    @staticmethod
    def _string_list(value, name: str) -> list[str]:
        if not isinstance(value, (list, tuple)) or not all(isinstance(item, str) and item for item in value):
            raise ValueError(f"{name} must contain non-empty strings")
        return list(value)


def create_plugin() -> ZaraCodingPlugin:
    return ZaraCodingPlugin()
