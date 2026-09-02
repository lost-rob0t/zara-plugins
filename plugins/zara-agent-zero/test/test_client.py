import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_agent_zero_service.client import AgentZeroBridgeError, AgentZeroClient
from zara_agent_zero_service.config import AgentZeroConfig


class FakeResponse:
    def __init__(self, payload: object):
        self.data = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit: int = -1):
        return self.data if limit < 0 else self.data[:limit]


class RecordingOpener:
    def __init__(self, payload: object):
        self.payload = payload
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        return FakeResponse(self.payload)


class AgentZeroClientTest(unittest.TestCase):
    def test_send_message_uses_native_endpoint_and_api_key(self):
        opener = RecordingOpener({"context_id": "ctx-1", "response": "done"})
        client = AgentZeroClient(
            AgentZeroConfig.load(
                {
                    "base_url": "http://localhost:5000",
                    "api_key": "secret-token",
                }
            ),
            opener=opener,
        )
        result = client.send_message("do work")
        request = opener.requests[0]
        self.assertEqual(result["response"], "done")
        self.assertTrue(request.full_url.endswith("/api/api_message"))
        self.assertEqual(request.get_header("X-api-key"), "secret-token")
        self.assertIsNone(request.get_header("Cookie"))

    def test_send_message_preserves_native_context_routing(self):
        opener = RecordingOpener({"context_id": "ctx-1", "response": "done"})
        client = AgentZeroClient(
            AgentZeroConfig.load(
                {
                    "base_url": "http://127.0.0.1:5000",
                    "api_key": "secret-token",
                }
            ),
            opener=opener,
        )
        client.send_message(
            "do work",
            context_id="ctx-1",
            project_name="demo",
            agent_profile="symbolics",
            lifetime_hours=12,
        )
        request_payload = json.loads(opener.requests[0].data.decode("utf-8"))
        self.assertEqual(
            request_payload,
            {
                "message": "do work",
                "context_id": "ctx-1",
                "project_name": "demo",
                "agent_profile": "symbolics",
                "lifetime_hours": 12.0,
            },
        )

    def test_status_reports_native_contract_without_transport(self):
        opener = RecordingOpener({})
        client = AgentZeroClient(
            AgentZeroConfig.load(
                {
                    "base_url": "http://localhost:5000",
                    "api_key": "secret-token",
                }
            ),
            opener=opener,
        )
        status = client.status()
        self.assertEqual(status["api"], "agent-zero-native")
        self.assertEqual(status["endpoint"], "/api/api_message")
        self.assertTrue(status["configured"])
        self.assertTrue(status["api_key_configured"])
        self.assertEqual(opener.requests, [])

    def test_missing_api_key_fails_before_transport(self):
        opener = RecordingOpener({})
        client = AgentZeroClient(
            AgentZeroConfig.load({"base_url": "http://localhost:5000"}),
            opener=opener,
        )
        with self.assertRaisesRegex(AgentZeroBridgeError, "api_key is not configured"):
            client.send_message("do work")
        self.assertEqual(opener.requests, [])

    def test_message_limit_is_enforced_before_transport(self):
        opener = RecordingOpener({})
        client = AgentZeroClient(
            AgentZeroConfig.load(
                {
                    "base_url": "http://localhost:5000",
                    "api_key": "secret-token",
                    "max_message_chars": 4,
                }
            ),
            opener=opener,
        )
        with self.assertRaisesRegex(AgentZeroBridgeError, "message exceeds"):
            client.send_message("12345")
        self.assertEqual(opener.requests, [])

    def test_lifetime_must_be_positive_before_transport(self):
        opener = RecordingOpener({})
        client = AgentZeroClient(
            AgentZeroConfig.load(
                {
                    "base_url": "http://localhost:5000",
                    "api_key": "secret-token",
                }
            ),
            opener=opener,
        )
        with self.assertRaisesRegex(AgentZeroBridgeError, "lifetime_hours"):
            client.send_message("do work", lifetime_hours=0)
        self.assertEqual(opener.requests, [])


if __name__ == "__main__":
    unittest.main()
