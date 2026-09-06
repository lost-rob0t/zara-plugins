"""Bounded GitHub REST client with verified mutation semantics."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Callable

from .config import GitHubConfig


class GitHubError(RuntimeError):
    pass


SUCCESSFUL_CONCLUSIONS = {"success", "neutral"}


class GitHubClient:
    def __init__(self, config: GitHubConfig, *, opener: Callable | None = None) -> None:
        self.config = config
        self._opener = opener or urllib.request.urlopen

    def _request(self, method: str, path: str, *, body: Any = None) -> Any:
        if not path.startswith("/"):
            raise GitHubError("GitHub request path must be absolute")
        url = f"{self.config.api_base}{path}"
        parsed = urllib.parse.urlsplit(url)
        base = urllib.parse.urlsplit(self.config.api_base)
        if (parsed.scheme, parsed.hostname, parsed.port) != (base.scheme, base.hostname, base.port):
            raise GitHubError("GitHub request escaped configured API origin")
        data = None if body is None else json.dumps(body).encode("utf-8")
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "zara-github/0.1.0",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.config.token:
            headers["Authorization"] = f"Bearer {self.config.token}"
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with self._opener(request, timeout=self.config.timeout_seconds) as response:
                payload = response.read(self.config.max_response_bytes + 1)
                if len(payload) > self.config.max_response_bytes:
                    raise GitHubError("GitHub response exceeded configured size limit")
        except urllib.error.HTTPError as error:
            raise GitHubError(f"GitHub request failed with HTTP {error.code}") from error
        except urllib.error.URLError as error:
            raise GitHubError(f"GitHub request failed: {error.reason}") from error
        except TimeoutError as error:
            raise GitHubError("GitHub request timed out") from error
        if not payload:
            return None
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GitHubError("GitHub returned malformed JSON") from error

    @staticmethod
    def _repo_path(repository: str) -> str:
        parts = repository.split("/")
        if len(parts) != 2 or not all(
            part
            and part.replace("-", "").replace("_", "").replace(".", "").isalnum()
            for part in parts
        ):
            raise GitHubError("repository must be owner/name")
        return "/".join(urllib.parse.quote(part, safe="") for part in parts)

    @staticmethod
    def _repository_from_api_url(url: str) -> str:
        parsed = urllib.parse.urlsplit(str(url))
        if parsed.scheme != "https" or parsed.hostname != "api.github.com":
            raise GitHubError("GitHub search returned an invalid repository URL")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 3 or parts[0] != "repos":
            raise GitHubError("GitHub search returned an invalid repository URL")
        return f"{parts[1]}/{parts[2]}"

    @staticmethod
    def _check_summary(runs: list[dict[str, Any]], head_sha: str) -> dict[str, int]:
        current = [run for run in runs if run.get("head_sha") == head_sha]
        successful = sum(
            1
            for run in current
            if run.get("status") == "completed"
            and run.get("conclusion") in SUCCESSFUL_CONCLUSIONS
        )
        pending = sum(1 for run in current if run.get("status") != "completed")
        failed = len(current) - successful - pending
        return {
            "total": len(current),
            "successful": successful,
            "pending": pending,
            "failed": failed,
        }

    @staticmethod
    def _object_number(number: int) -> int:
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise GitHubError("number must be a positive integer")
        return number

    def _result_limit(self, limit: int | None) -> int:
        if limit is None:
            return self.config.max_results
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise GitHubError("limit must be a positive integer")
        return min(limit, self.config.max_results)

    def repo_get(self, repository: str) -> Any:
        return self._request("GET", f"/repos/{self._repo_path(repository)}")

    def pr_get(self, repository: str, number: int) -> Any:
        number = self._object_number(number)
        return self._request("GET", f"/repos/{self._repo_path(repository)}/pulls/{number}")

    def pr_diff(self, repository: str, number: int) -> Any:
        number = self._object_number(number)
        return self._request(
            "GET", f"/repos/{self._repo_path(repository)}/pulls/{number}/files?per_page=100"
        )

    def pr_checks(self, repository: str, number: int) -> dict[str, Any]:
        pull = self.pr_get(repository, number)
        head_sha = str(pull.get("head", {}).get("sha", ""))
        if not head_sha:
            raise GitHubError("pull request has no current head SHA")
        checks = self._request(
            "GET",
            f"/repos/{self._repo_path(repository)}/commits/{urllib.parse.quote(head_sha, safe='')}/check-runs?per_page=100",
        )
        return {
            "head_sha": head_sha,
            "check_runs": list((checks or {}).get("check_runs", [])),
        }

    def pr_reviews(self, repository: str, number: int) -> Any:
        number = self._object_number(number)
        return self._request(
            "GET", f"/repos/{self._repo_path(repository)}/pulls/{number}/reviews?per_page=100"
        )

    def pr_list(self, repository: str, *, state: str = "open", limit: int | None = None) -> Any:
        count = self._result_limit(limit)
        encoded_state = urllib.parse.quote(state, safe="")
        return self._request(
            "GET",
            f"/repos/{self._repo_path(repository)}/pulls?state={encoded_state}&sort=updated&direction=desc&per_page={count}",
        )

    def latest_prs(self, *, limit: int | None = None) -> list[dict[str, Any]]:
        if not self.config.owner:
            raise GitHubError("owner must be configured for latest PRs")
        count = self._result_limit(limit)
        query = urllib.parse.quote(f"is:pr author:{self.config.owner}", safe="")
        search = self._request(
            "GET", f"/search/issues?q={query}&sort=updated&order=desc&per_page={count}"
        )
        results: list[dict[str, Any]] = []
        for item in list((search or {}).get("items", []))[:count]:
            repository = self._repository_from_api_url(str(item.get("repository_url", "")))
            number = int(item["number"])
            pull = self.pr_get(repository, number)
            head_sha = str(pull.get("head", {}).get("sha", ""))
            if not head_sha:
                raise GitHubError(f"{repository}#{number} has no current head SHA")
            checks = self._request(
                "GET",
                f"/repos/{self._repo_path(repository)}/commits/{urllib.parse.quote(head_sha, safe='')}/check-runs?per_page=100",
            )
            runs = list((checks or {}).get("check_runs", []))
            results.append(
                {
                    "provider": "github",
                    "repository": repository,
                    "number": number,
                    "title": str(pull.get("title", item.get("title", ""))),
                    "head_sha": head_sha,
                    "draft": bool(pull.get("draft", False)),
                    "mergeable": pull.get("mergeable"),
                    "checks": self._check_summary(runs, head_sha),
                    "updated_at": pull.get("updated_at", item.get("updated_at")),
                    "url": pull.get("html_url", item.get("html_url")),
                }
            )
        return results

    def issue_list(self, repository: str, *, state: str = "open", limit: int | None = None) -> Any:
        count = self._result_limit(limit)
        encoded_state = urllib.parse.quote(state, safe="")
        return self._request(
            "GET", f"/repos/{self._repo_path(repository)}/issues?state={encoded_state}&per_page={count}"
        )

    def issue_get(self, repository: str, number: int) -> Any:
        number = self._object_number(number)
        return self._request("GET", f"/repos/{self._repo_path(repository)}/issues/{number}")

    def commit_status(self, repository: str, sha: str) -> Any:
        return self._request(
            "GET",
            f"/repos/{self._repo_path(repository)}/commits/{urllib.parse.quote(sha, safe='')}/status",
        )

    def issue_create(self, repository: str, title: str, body: str = "") -> Any:
        if not title.strip() or len(title) > 256 or len(body) > 65536:
            raise GitHubError("issue title/body is invalid or too large")
        return self._request(
            "POST",
            f"/repos/{self._repo_path(repository)}/issues",
            body={"title": title, "body": body},
        )

    def issue_update(
        self,
        repository: str,
        number: int,
        *,
        title: str = "",
        body: str = "",
        state: str = "",
    ) -> Any:
        number = self._object_number(number)
        payload: dict[str, Any] = {}
        if title:
            if len(title) > 256:
                raise GitHubError("issue title is too large")
            payload["title"] = title
        if body:
            if len(body) > 65536:
                raise GitHubError("issue body is too large")
            payload["body"] = body
        if state:
            if state not in {"open", "closed"}:
                raise GitHubError("issue state must be open or closed")
            payload["state"] = state
        if not payload:
            raise GitHubError("issue update requires at least one field")
        return self._request(
            "PATCH",
            f"/repos/{self._repo_path(repository)}/issues/{number}",
            body=payload,
        )

    def pr_comment(self, repository: str, number: int, body: str) -> Any:
        number = self._object_number(number)
        if not body.strip() or len(body) > 65536:
            raise GitHubError("comment body is invalid or too large")
        return self._request(
            "POST",
            f"/repos/{self._repo_path(repository)}/issues/{number}/comments",
            body={"body": body},
        )

    def merge_pull_request(
        self, repository: str, number: int, *, method: str = "squash"
    ) -> dict[str, Any]:
        number = self._object_number(number)
        if method not in {"merge", "squash", "rebase"}:
            raise GitHubError("merge method must be merge, squash, or rebase")
        pull = self.pr_get(repository, number)
        if pull.get("draft"):
            raise GitHubError("pull request is draft")
        if pull.get("mergeable") is not True:
            raise GitHubError("pull request is not currently mergeable")
        head_sha = str(pull.get("head", {}).get("sha", ""))
        if not head_sha:
            raise GitHubError("pull request has no current head SHA")
        checks = self._request(
            "GET",
            f"/repos/{self._repo_path(repository)}/commits/{urllib.parse.quote(head_sha, safe='')}/check-runs?per_page=100",
        )
        runs = list((checks or {}).get("check_runs", []))
        if not runs or any(
            run.get("head_sha") != head_sha
            or run.get("status") != "completed"
            or run.get("conclusion") not in SUCCESSFUL_CONCLUSIONS
            for run in runs
        ):
            raise GitHubError("current-head checks are not conclusively successful")
        reviews = self.pr_reviews(repository, number)
        if any(
            str(review.get("state", "")).upper() == "CHANGES_REQUESTED"
            for review in (reviews or [])
        ):
            raise GitHubError("pull request has a blocking review")
        acknowledgement = self._request(
            "PUT",
            f"/repos/{self._repo_path(repository)}/pulls/{number}/merge",
            body={"sha": head_sha, "merge_method": method},
        )
        if (
            not isinstance(acknowledgement, dict)
            or acknowledgement.get("merged") is not True
            or not acknowledgement.get("sha")
        ):
            raise GitHubError("GitHub did not acknowledge a successful merge")
        observed = self.pr_get(repository, number)
        observed_head = str(observed.get("head", {}).get("sha", ""))
        if observed_head != head_sha:
            raise GitHubError("pull request head changed during merge verification")
        if observed.get("merged") is not True:
            raise GitHubError("post-merge verification did not observe merged state")
        merge_sha = str(acknowledgement.get("sha"))
        if str(observed.get("merge_commit_sha", "")) != merge_sha:
            raise GitHubError("post-merge verification observed a different merge commit")
        return {
            "merged": True,
            "repository": repository,
            "number": number,
            "head_sha": head_sha,
            "merge_commit_sha": merge_sha,
        }
