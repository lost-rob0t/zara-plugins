from __future__ import annotations

import json
import shutil
from collections.abc import Mapping, Sequence
from pathlib import Path

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import PrologRLMBridge, RepositoryInspector
from .repository_evidence import build_repository_evidence
from .spec_compile import catalog_spec, compile_spec
from .spec_verify import verify_repository_spec as verify_repository_spec_pure
from .worktree import add_detached_locked_worktree, add_detached_worktree, lock_worktree, unlock_worktree


PLUGIN_VERSION = "0.1.0"
APPROVAL_METADATA = {"zara_requires_approval": True}


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
            StructuredTool.from_function(func=self.status, name="coding.status", description="Report repository-boundary and Prolog-RLM readiness without mutating state."),
            StructuredTool.from_function(func=self.list_repositories, name="coding.repo.list", description="List bounded immediate Git repository roots under configured repository boundaries."),
            StructuredTool.from_function(func=self.repo_status, name="coding.repo.status", description="Return branch/head/dirty status for one allowed repository."),
            StructuredTool.from_function(func=self.inspect_repo, name="coding.repo.inspect", description="Return structured Git branch/head/dirty evidence for an allowed repository."),
            StructuredTool.from_function(func=self.git_diff, name="coding.git.diff", description="Return bounded structured working-tree diff statistics for an allowed repository."),
            StructuredTool.from_function(func=self.git_log, name="coding.git.log", description="Return bounded structured commit history for an allowed repository."),
            StructuredTool.from_function(func=self.git_branches, name="coding.git.branches", description="Return bounded structured local branch refs for an allowed repository."),
            StructuredTool.from_function(func=self.git_branch_create, name="coding.git.branch.create", description="Create one new local branch at the repository's current HEAD without moving an existing ref.", metadata=APPROVAL_METADATA),
            StructuredTool.from_function(func=self.git_branch_delete, name="coding.git.branch.delete", description="Delete one local branch only if it still points at the caller-supplied full object ID and is not checked out.", metadata=APPROVAL_METADATA),
            StructuredTool.from_function(func=self.git_commit, name="coding.git.commit", description="Commit exactly the current staged index on the attached branch if HEAD still matches the caller-supplied full object ID.", metadata=APPROVAL_METADATA),
            StructuredTool.from_function(func=self.git_worktrees, name="coding.git.worktree.list", description="Return bounded structured linked-worktree evidence for an allowed repository."),
            StructuredTool.from_function(func=self.git_worktree_add_detached, name="coding.git.worktree.add-detached", description="Create one detached linked worktree at an exact commit inside configured repository boundaries.", metadata=APPROVAL_METADATA),
            StructuredTool.from_function(func=self.git_worktree_add_detached_locked, name="coding.git.worktree.add-detached-locked", description="Create one detached linked worktree at an exact commit and immediately coordination-lock it with a bounded reason.", metadata=APPROVAL_METADATA),
            StructuredTool.from_function(func=self.git_worktree_lock, name="coding.git.worktree.lock", description="Ownership-lock one detached linked worktree at an exact observed commit with a bounded reason.", metadata=APPROVAL_METADATA),
            StructuredTool.from_function(func=self.git_worktree_unlock, name="coding.git.worktree.unlock", description="Unlock one detached linked worktree only when exact HEAD and lock reason still match.", metadata=APPROVAL_METADATA),
            StructuredTool.from_function(func=self.spec_catalog, name="coding.spec.catalog", description="Return Prolog-RLM's closed SPEC vocabulary and zara-coding's fixed trusted assertion catalog."),
            StructuredTool.from_function(func=self.normalize_spec, name="coding.spec.normalize", description="Normalize one closed declarative SPEC source through Prolog-RLM and return its canonical outcome without validation, freezing, planning or mutation."),
            StructuredTool.from_function(func=self.compile_spec, name="coding.spec.compile", description="Validate and freeze one closed SPEC through zara-coding's fixed trusted Prolog-RLM assertion registry."),
            StructuredTool.from_function(func=self.verify_repository_spec, name="coding.spec.verify-repository", description="Reconcile one frozen SPEC against a fresh bounded repository snapshot using Prolog-RLM's pure verifier."),
            StructuredTool.from_function(func=self.check_repository_spec, name="coding.spec.check-repository", description="Compile one declarative SPEC and, only if freezing succeeds, verify it against the current allowed repository state."),
        )

    def status(self) -> str:
        repository = ({"status": "ready"} if self.inspector is not None else {"status": "unavailable", "reason": self.repository_reason})
        prolog_rlm = (self.prolog_rlm.status() if self.prolog_rlm is not None else {"status": "unavailable", "reason": "prolog-rlm-checkout-not-configured"})
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

    def git_branch_create(self, path: str, name: str) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        return json.dumps(inspector.create_branch(Path(path), name), sort_keys=True)

    def git_branch_delete(self, path: str, name: str, expected_head: str) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if not isinstance(name, str) or not name:
            raise ValueError("name must be a non-empty string")
        if not isinstance(expected_head, str) or not expected_head:
            raise ValueError("expected_head must be a non-empty string")
        return json.dumps(inspector.delete_branch(Path(path), name, expected_head), sort_keys=True)

    def git_commit(self, path: str, message: str, expected_head: str) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("message must be a non-empty string")
        if not isinstance(expected_head, str) or not expected_head:
            raise ValueError("expected_head must be a non-empty string")
        return json.dumps(inspector.commit(Path(path), message, expected_head), sort_keys=True)

    def git_worktrees(self, path: str, limit: int = 50) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        return json.dumps(inspector.worktrees(Path(path), limit=limit), sort_keys=True)

    def git_worktree_add_detached(self, path: str, target: str, expected_head: str) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if not isinstance(target, str) or not target:
            raise ValueError("target must be a non-empty string")
        if not isinstance(expected_head, str) or not expected_head:
            raise ValueError("expected_head must be a non-empty string")
        return json.dumps(add_detached_worktree(inspector, Path(path), Path(target), expected_head), sort_keys=True)

    def git_worktree_add_detached_locked(self, path: str, target: str, expected_head: str, reason: str) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if not isinstance(target, str) or not target:
            raise ValueError("target must be a non-empty string")
        if not isinstance(expected_head, str) or not expected_head:
            raise ValueError("expected_head must be a non-empty string")
        if not isinstance(reason, str) or not reason:
            raise ValueError("reason must be a non-empty string")
        return json.dumps(add_detached_locked_worktree(inspector, Path(path), Path(target), expected_head, reason), sort_keys=True)

    def git_worktree_lock(self, path: str, target: str, expected_head: str, reason: str) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if not isinstance(target, str) or not target:
            raise ValueError("target must be a non-empty string")
        if not isinstance(expected_head, str) or not expected_head:
            raise ValueError("expected_head must be a non-empty string")
        if not isinstance(reason, str) or not reason:
            raise ValueError("reason must be a non-empty string")
        return json.dumps(lock_worktree(inspector, Path(path), Path(target), expected_head, reason), sort_keys=True)

    def git_worktree_unlock(self, path: str, target: str, expected_head: str, reason: str) -> str:
        inspector = self._require_inspector()
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if not isinstance(target, str) or not target:
            raise ValueError("target must be a non-empty string")
        if not isinstance(expected_head, str) or not expected_head:
            raise ValueError("expected_head must be a non-empty string")
        if not isinstance(reason, str) or not reason:
            raise ValueError("reason must be a non-empty string")
        return json.dumps(unlock_worktree(inspector, Path(path), Path(target), expected_head, reason), sort_keys=True)

    def spec_catalog(self) -> str:
        return json.dumps(catalog_spec(self._require_prolog_rlm()), sort_keys=True)

    def normalize_spec(self, source: str) -> str:
        bridge = self._require_prolog_rlm()
        return json.dumps(bridge.normalize_spec(source), sort_keys=True)

    def compile_spec(self, source: str) -> str:
        return json.dumps(compile_spec(self._require_prolog_rlm(), source), sort_keys=True)

    def verify_repository_spec(self, path: str, frozen_spec: str) -> str:
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if not isinstance(frozen_spec, str) or not frozen_spec.strip():
            raise ValueError("frozen_spec must be a non-empty string")
        inspector = self._require_inspector()
        bridge = self._require_prolog_rlm()
        repository = Path(path)
        snapshot = inspector.inspect(repository)
        worktrees = inspector.worktrees(repository, limit=100)
        evidence = build_repository_evidence(snapshot, worktrees=worktrees)
        return json.dumps(verify_repository_spec_pure(bridge, frozen_spec, evidence), sort_keys=True)

    def check_repository_spec(self, path: str, source: str) -> str:
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a non-empty string")
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-empty string")
        bridge = self._require_prolog_rlm()
        compiled = compile_spec(bridge, source)
        if compiled.get("status") != "ok":
            return json.dumps({"compile": compiled, "verification": None}, sort_keys=True)
        verification = json.loads(self.verify_repository_spec(path, compiled["outcome"]))
        return json.dumps({"compile": compiled, "verification": verification}, sort_keys=True)

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
