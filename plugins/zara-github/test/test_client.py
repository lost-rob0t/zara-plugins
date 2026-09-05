import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_github.client import GitHubClient, GitHubError
from zara_github.config import GitHubConfig


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit=-1):
        return self.payload if limit < 0 else self.payload[:limit]


class QueueOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        if not self.responses:
            raise AssertionError("unexpected GitHub request")
        return FakeResponse(self.responses.pop(0))


class GitHubClientTest(unittest.TestCase):
    def client(self, responses):
        opener = QueueOpener(responses)
        client = GitHubClient(
            GitHubConfig(token="secret-token", owner="lost-rob0t"),
            opener=opener,
        )
        return client, opener

    def test_latest_prs_hydrates_current_provider_state(self):
        client, _ = self.client(
            [
                {
                    "items": [
                        {
                            "number": 55,
                            "title": "Add GitHub provider",
                            "repository_url": "https://api.github.com/repos/lost-rob0t/zara-plugins",
                            "html_url": "https://github.com/lost-rob0t/zara-plugins/pull/55",
                            "updated_at": "2026-09-05T07:22:22Z",
                        }
                    ]
                },
                {
                    "number": 55,
                    "title": "Add GitHub provider",
                    "draft": False,
                    "mergeable": True,
                    "head": {"sha": "abc123"},
                    "html_url": "https://github.com/lost-rob0t/zara-plugins/pull/55",
                    "updated_at": "2026-09-05T07:22:22Z",
                },
                {
                    "check_runs": [
                        {
                            "name": "CI",
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc123",
                        }
                    ]
                },
            ]
        )

        result = client.latest_prs(limit=1)

        self.assertEqual(
            result,
            [
                {
                    "provider": "github",
                    "repository": "lost-rob0t/zara-plugins",
                    "number": 55,
                    "title": "Add GitHub provider",
                    "head_sha": "abc123",
                    "draft": False,
                    "mergeable": True,
                    "checks": {"total": 1, "successful": 1, "pending": 0, "failed": 0},
                    "updated_at": "2026-09-05T07:22:22Z",
                    "url": "https://github.com/lost-rob0t/zara-plugins/pull/55",
                }
            ],
        )

    def test_merge_rejects_pending_exact_head_checks_before_mutation(self):
        client, opener = self.client(
            [
                {
                    "number": 50,
                    "draft": False,
                    "mergeable": True,
                    "head": {"sha": "abc123"},
                },
                {
                    "check_runs": [
                        {
                            "name": "CI",
                            "status": "in_progress",
                            "conclusion": None,
                            "head_sha": "abc123",
                        }
                    ]
                },
            ]
        )

        with self.assertRaisesRegex(GitHubError, "checks are not conclusively successful"):
            client.merge_pull_request("lost-rob0t/zara-plugins", 50)

        self.assertEqual(len(opener.requests), 2)
        self.assertTrue(all(request.method == "GET" for request in opener.requests))

    def test_merge_sends_expected_head_and_verifies_provider_state(self):
        client, opener = self.client(
            [
                {
                    "number": 50,
                    "draft": False,
                    "mergeable": True,
                    "head": {"sha": "abc123"},
                },
                {
                    "check_runs": [
                        {
                            "name": "CI",
                            "status": "completed",
                            "conclusion": "success",
                            "head_sha": "abc123",
                        }
                    ]
                },
                [],
                {"merged": True, "sha": "merge456", "message": "Pull Request successfully merged"},
                {
                    "number": 50,
                    "merged": True,
                    "merge_commit_sha": "merge456",
                    "head": {"sha": "abc123"},
                },
            ]
        )

        result = client.merge_pull_request("lost-rob0t/zara-plugins", 50)

        self.assertTrue(result["merged"])
        self.assertEqual(result["head_sha"], "abc123")
        merge_request = opener.requests[3]
        self.assertEqual(merge_request.method, "PUT")
        body = json.loads(merge_request.data.decode("utf-8"))
        self.assertEqual(body["sha"], "abc123")

    def test_merge_rejects_head_movement_during_post_verification(self):
        client, opener = self.client(
            [
                {"number": 50, "draft": False, "mergeable": True, "head": {"sha": "abc123"}},
                {"check_runs": [{"name": "CI", "status": "completed", "conclusion": "success", "head_sha": "abc123"}]},
                [],
                {"merged": True, "sha": "merge456"},
                {"number": 50, "merged": True, "merge_commit_sha": "merge456", "head": {"sha": "moved999"}},
            ]
        )

        with self.assertRaisesRegex(GitHubError, "head changed"):
            client.merge_pull_request("lost-rob0t/zara-plugins", 50)


if __name__ == "__main__":
    unittest.main()
