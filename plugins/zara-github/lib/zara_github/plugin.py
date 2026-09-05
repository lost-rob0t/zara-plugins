"""Zara service plugin for typed GitHub operations."""

from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .client import GitHubClient
from .config import GitHubConfig


PLUGIN_VERSION = "0.1.0"


class ZaraGitHubPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-github",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Typed GitHub PR, issue, check, review, and merge operations",
    )

    def __init__(self) -> None:
        self._config = GitHubConfig()
        self._client = GitHubClient(self._config)

    def start(self, runtime) -> None:
        self._config = GitHubConfig.load(runtime.configuration)
        self._client = GitHubClient(self._config)

    def stop(self) -> None:
        return None

    def tools(self):
        functions = (
            (self.latest_prs, "github.pr.latest", "List the operator's latest relevant pull requests from live GitHub state."),
            (self.pr_list, "github.pr.list", "List pull requests for an exact repository."),
            (self.pr_get, "github.pr.get", "Get one pull request by exact repository and number."),
            (self.pr_diff, "github.pr.diff", "Get bounded changed-file data for one pull request."),
            (self.pr_checks, "github.pr.checks", "Get exact-current-head GitHub check runs for one pull request."),
            (self.pr_reviews, "github.pr.reviews", "Get reviews for one pull request."),
            (self.issue_list, "github.issue.list", "List issues for an exact repository."),
            (self.issue_get, "github.issue.get", "Get one issue by exact repository and number."),
            (self.repo_get, "github.repo.get", "Get repository metadata."),
            (self.commit_status, "github.commit.status", "Get combined commit status for an exact repository and SHA."),
            (self.merge_pr, "github.pr.merge", "Merge only after exact-head checks and review gates pass, then verify merged state."),
            (self.issue_create, "github.issue.create", "Create an issue through a bounded typed mutation."),
            (self.issue_update, "github.issue.update", "Update bounded issue fields through GitHub."),
            (self.pr_comment, "github.pr.comment", "Add a bounded comment to a pull request conversation."),
        )
        return tuple(
            StructuredTool.from_function(func=function, name=name, description=description)
            for function, name, description in functions
        )

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def latest_prs(self, limit: int = 20) -> str:
        return self._json(self._client.latest_prs(limit=limit))

    def pr_list(self, repository: str, state: str = "open", limit: int = 20) -> str:
        return self._json(self._client.pr_list(repository, state=state, limit=limit))

    def pr_get(self, repository: str, number: int) -> str:
        return self._json(self._client.pr_get(repository, number))

    def pr_diff(self, repository: str, number: int) -> str:
        return self._json(self._client.pr_diff(repository, number))

    def pr_checks(self, repository: str, number: int) -> str:
        return self._json(self._client.pr_checks(repository, number))

    def pr_reviews(self, repository: str, number: int) -> str:
        return self._json(self._client.pr_reviews(repository, number))

    def issue_list(self, repository: str, state: str = "open", limit: int = 20) -> str:
        return self._json(self._client.issue_list(repository, state=state, limit=limit))

    def issue_get(self, repository: str, number: int) -> str:
        return self._json(self._client.issue_get(repository, number))

    def repo_get(self, repository: str) -> str:
        return self._json(self._client.repo_get(repository))

    def commit_status(self, repository: str, sha: str) -> str:
        return self._json(self._client.commit_status(repository, sha))

    def merge_pr(self, repository: str, number: int, method: str = "squash") -> str:
        return self._json(self._client.merge_pull_request(repository, number, method=method))

    def issue_create(self, repository: str, title: str, body: str = "") -> str:
        return self._json(self._client.issue_create(repository, title, body))

    def issue_update(self, repository: str, number: int, title: str = "", body: str = "", state: str = "") -> str:
        return self._json(self._client.issue_update(repository, number, title=title, body=body, state=state))

    def pr_comment(self, repository: str, number: int, body: str) -> str:
        return self._json(self._client.pr_comment(repository, number, body))


def create_plugin():
    return ZaraGitHubPlugin()
