import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_knowledge.brave import BraveProvider, BraveProviderError
from zara_knowledge.core import KnowledgeEngine, SourcedResult


class FakeProvider:
    def __init__(self, name, results=None, error=None, local=False):
        self.name = name
        self.local = local
        self.results = list(results or [])
        self.error = error

    def search(self, query, *, count=5, **parameters):
        if self.error:
            raise self.error
        return self.results[:count]


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit=-1):
        data = self.payload if isinstance(self.payload, bytes) else json.dumps(self.payload).encode()
        return data if limit < 0 else data[:limit]


class QueueOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class KnowledgeEngineTest(unittest.TestCase):
    def test_provenance_and_conflicts_survive_merge(self):
        remote = FakeProvider(
            "remote",
            [SourcedResult("remote", "https://a.example/x", "A", "value is one", "2026-09-05T00:00:00Z", False)],
        )
        local = FakeProvider(
            "local-kb",
            [SourcedResult("local-kb", "local://facts/x", "A", "value is two", "2026-09-05T00:00:01Z", True)],
            local=True,
        )
        engine = KnowledgeEngine([remote, local])

        result = engine.search("value", count=5)

        self.assertEqual(len(result["results"]), 2)
        self.assertEqual({item["provider"] for item in result["results"]}, {"remote", "local-kb"})
        self.assertEqual({item["local"] for item in result["results"]}, {False, True})
        self.assertEqual(result["errors"], [])

    def test_provider_failure_degrades_independently(self):
        good = FakeProvider(
            "good",
            [SourcedResult("good", "https://good.example/", "Good", "ok", "2026-09-05T00:00:00Z", False)],
        )
        bad = FakeProvider("bad", error=RuntimeError("provider down"))

        result = KnowledgeEngine([bad, good]).search("query")

        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["errors"][0]["provider"], "bad")
        self.assertEqual(result["errors"][0]["kind"], "unavailable")


class BraveProviderTest(unittest.TestCase):
    def provider(self, responses, **kwargs):
        opener = QueueOpener(responses)
        provider = BraveProvider(api_key="secret-key", opener=opener, **kwargs)
        return provider, opener

    def test_maps_brave_results_to_provider_neutral_schema(self):
        provider, opener = self.provider(
            [
                FakeResponse(
                    {
                        "web": {
                            "results": [
                                {
                                    "title": "Example",
                                    "url": "https://example.com/page",
                                    "description": "bounded snippet",
                                    "age": "2 hours ago",
                                }
                            ]
                        }
                    }
                )
            ]
        )

        results = provider.search("example", count=1, language="en", safe_search="moderate")

        self.assertEqual(results[0].provider, "brave")
        self.assertEqual(results[0].url, "https://example.com/page")
        self.assertFalse(results[0].local)
        request = opener.requests[0]
        self.assertEqual(request.headers["X-subscription-token"], "secret-key")
        self.assertNotIn("secret-key", request.full_url)

    def test_rejects_invalid_returned_url(self):
        provider, _ = self.provider(
            [FakeResponse({"web": {"results": [{"title": "Bad", "url": "javascript:alert(1)", "description": "x"}]}})]
        )
        with self.assertRaisesRegex(BraveProviderError, "invalid result URL"):
            provider.search("bad")

    def test_zero_results_is_real_success(self):
        provider, _ = self.provider([FakeResponse({"web": {"results": []}})])
        self.assertEqual(provider.search("nothing"), [])

    def test_malformed_response_is_typed_failure_without_secret(self):
        provider, _ = self.provider([FakeResponse(b"not-json")])
        with self.assertRaises(BraveProviderError) as caught:
            provider.search("bad")
        self.assertEqual(caught.exception.kind, "malformed_response")
        self.assertNotIn("secret-key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
