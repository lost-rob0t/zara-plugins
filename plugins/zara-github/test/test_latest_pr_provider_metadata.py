import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_github.client import GitHubClient, GitHubError
from zara_github.config import GitHubConfig


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

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


class LatestPrProviderMetadataTest(unittest.TestCase):
    def client(self, responses):
        opener = QueueOpener(responses)
        return GitHubClient(
            GitHubConfig(token="secret-token", owner="lost-rob0t"),
            opener=opener,
        ), opener

    @staticmethod
    def search_item(number=55):
        return {
            "number": number,
            "title": "PR",
            "repository_url": "https://api.github.com/repos/lost-rob0t/zara-plugins",
            "html_url": "https://github.com/lost-rob0t/zara-plugins/pull/55",
            "updated_at": "2026-09-07T00:00:00Z",
        }

    @staticmethod
    def pull(*, draft=False, mergeable=True):
        return {
            "number": 55,
            "title": "PR",
            "draft": draft,
            "mergeable": mergeable,
            "head": {"sha": "abc123"},
            "html_url": "https://github.com/lost-rob0t/zara-plugins/pull/55",
            "updated_at": "2026-09-07T00:00:00Z",
        }

    def test_search_number_rejects_coercible_non_integers(self):
        for malformed in (True, "55", 55.0):
            with self.subTest(number=malformed):
                client, opener = self.client([{"items": [self.search_item(malformed)]}])
                with self.assertRaisesRegex(GitHubError, "number"):
                    client.latest_prs(limit=1)
                self.assertEqual(len(opener.requests), 1)

    def test_draft_requires_exact_boolean(self):
        client, opener = self.client([
            {"items": [self.search_item()]},
            self.pull(draft="false"),
        ])
        with self.assertRaisesRegex(GitHubError, "draft"):
            client.latest_prs(limit=1)
        self.assertEqual(len(opener.requests), 2)

    def test_mergeable_requires_boolean_or_none(self):
        client, opener = self.client([
            {"items": [self.search_item()]},
            self.pull(mergeable="true"),
        ])
        with self.assertRaisesRegex(GitHubError, "mergeable"):
            client.latest_prs(limit=1)
        self.assertEqual(len(opener.requests), 2)


if __name__ == "__main__":
    unittest.main()
