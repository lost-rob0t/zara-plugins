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
    def test_capabilities_uses_connector_endpoint_and_cookie(self):
        opener = RecordingOpener(
            {"protocol": "a0-connector.v1", "features": ["message_send"]}
        )
        client = AgentZeroClient(
            AgentZeroConfig.load(
                {
                    "base_url": "http://localhost:5000",
                    "session_cookie": "session=secret",
                }
            ),
            opener=opener,
        )
        result = client.capabilities()
        request = opener.requests[0]
        self.assertEqual(result["protocol"], "a0-connector.v1")
        self.assertTrue(request.full_url.endswith("/api/plugins/_a0_connector/v1/capabilities"))
        self.assertEqual(request.get_header("Cookie"), "session=secret")

    def test_send_message_preserves_context_routing(self):
        opener = RecordingOpener(
            {"context_id": "ctx-1", "status": "completed", "response": "done"}
        )
        client = AgentZeroClient(
            AgentZeroConfig.load({"base_url": "http://127.0.0.1:5000"}),
            opener=opener,
        )
        result = client.send_message(
            "do work",
            context_id="ctx-1",
            project_name="demo",
            agent_profile="symbolics",
        )
        request_payload = json.loads(opener.requests[0].data.decode("utf-8"))
        self.assertEqual(result["response"], "done")
        self.assertEqual(
            request_payload,
            {
                "message": "do work",
                "context_id": "ctx-1",
                "project_name": "demo",
                "agent_profile": "symbolics",
            },
        )

    def test_message_limit_is_enforced_before_transport(self):
        opener = RecordingOpener({})
        client = AgentZeroClient(
            AgentZeroConfig.load(
                {"base_url": "http://localhost:5000", "max_message_chars": 4}
            ),
            opener=opener,
        )
        with self.assertRaisesRegex(AgentZeroBridgeError, "message exceeds"):
            client.send_message("12345")
        self.assertEqual(opener.requests, [])

    def test_protocol_mismatch_fails_closed(self):
        client = AgentZeroClient(
            AgentZeroConfig.load({"base_url": "http://localhost:5000"}),
            opener=RecordingOpener({"protocol": "something-else"}),
        )
        with self.assertRaisesRegex(AgentZeroBridgeError, "incompatible"):
            client.capabilities()


if __name__ == "__main__":
    unittest.main()
