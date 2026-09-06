import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_github.client import GitHubClient, GitHubError
from zara_github.config import GitHubConfig


class GitHubNumberValidationTests(unittest.TestCase):
    def test_rejects_malformed_issue_and_pr_numbers_before_network(self):
        def opener(*args, **kwargs):
            self.fail("network opener must not be called")

        client = GitHubClient(GitHubConfig(), opener=opener)
        calls = (
            lambda number: client.pr_get("owner/repo", number),
            lambda number: client.pr_diff("owner/repo", number),
            lambda number: client.pr_reviews("owner/repo", number),
            lambda number: client.pr_checks("owner/repo", number),
            lambda number: client.merge_pull_request("owner/repo", number),
            lambda number: client.issue_get("owner/repo", number),
            lambda number: client.issue_update("owner/repo", number, state="closed"),
            lambda number: client.pr_comment("owner/repo", number, "reviewed"),
        )

        for number in (True, False, 0, -1, 1.5, "1"):
            for call in calls:
                with self.subTest(number=number, call=call):
                    with self.assertRaisesRegex(GitHubError, "positive integer"):
                        call(number)


if __name__ == "__main__":
    unittest.main()
