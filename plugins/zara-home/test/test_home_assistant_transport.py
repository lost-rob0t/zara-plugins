import json
import socket
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_home.home_assistant_transport import HomeAssistantHTTPError, HomeAssistantHTTPTransport


class _State:
    token = "token-a"
    refreshes = 0
    requests = []
    mode = "ok"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        return

    def _send(self, code, body):
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_GET(self):
        _State.requests.append((self.path, self.headers.get("Authorization")))
        if _State.mode == "401-once" and len(_State.requests) == 1:
            self._send(401, {"message": "unauthorized"})
            return
        if _State.mode == "malformed":
            self._send(200, b"not-json")
            return
        if _State.mode == "429":
            self._send(429, {"message": "slow down"})
            return
        if _State.mode == "503":
            self._send(503, {"message": "temporarily unavailable"})
            return
        if _State.mode == "timeout":
            time.sleep(0.2)
            self._send(200, {"entity_id": "light.office", "state": "on", "attributes": {}})
            return
        if _State.mode == "disconnect":
            self.connection.shutdown(socket.SHUT_RDWR)
            self.connection.close()
            return
        if self.headers.get("Authorization") != f"Bearer {_State.token}":
            self._send(403, {"message": "forbidden"})
            return
        self._send(200, {"entity_id": "light.office", "state": "on", "attributes": {}})


class HomeAssistantHTTPTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        _State.token = "token-a"
        _State.requests = []
        _State.mode = "ok"

    def test_injects_bearer_without_secret_in_evidence(self):
        transport = HomeAssistantHTTPTransport(self.base_url, "token-a")
        result = transport.request("GET", "/api/states/light.office")
        self.assertEqual(result["entity_id"], "light.office")
        self.assertEqual(_State.requests[-1][1], "Bearer token-a")
        self.assertNotIn("token-a", repr(result))

    def test_rejects_unsafe_initial_bearer_without_secret_evidence(self):
        secret = "initial-secret\r\nX-Evil: injected"
        with self.assertRaisesRegex(HomeAssistantHTTPError, "invalid-access-token") as caught:
            HomeAssistantHTTPTransport(self.base_url, secret)
        self.assertNotIn(secret, str(caught.exception))
        self.assertEqual(_State.requests, [])

    def test_401_refreshes_once_then_retries(self):
        _State.mode = "401-once"

        def refresh():
            _State.token = "token-b"
            return "token-b"

        transport = HomeAssistantHTTPTransport(self.base_url, "token-a", refresh_token=refresh)
        result = transport.request("GET", "/api/states/light.office")
        self.assertEqual(result["state"], "on")
        self.assertEqual(len(_State.requests), 2)
        self.assertEqual(_State.requests[-1][1], "Bearer token-b")

    def test_refresh_failure_is_explicit_and_secret_safe(self):
        _State.mode = "401-once"
        transport = HomeAssistantHTTPTransport(self.base_url, "token-a", refresh_token=lambda: None)
        with self.assertRaisesRegex(HomeAssistantHTTPError, "reauth-required") as caught:
            transport.request("GET", "/api/states/light.office")
        self.assertNotIn("token-a", str(caught.exception))
        self.assertEqual(len(_State.requests), 1)

    def test_rejects_unsafe_refreshed_bearer_without_secret_evidence(self):
        _State.mode = "401-once"
        secret = "refresh-secret\r\nX-Evil: injected"
        transport = HomeAssistantHTTPTransport(self.base_url, "token-a", refresh_token=lambda: secret)
        with self.assertRaisesRegex(HomeAssistantHTTPError, "reauth-required") as caught:
            transport.request("GET", "/api/states/light.office")
        self.assertNotIn(secret, str(caught.exception))
        self.assertEqual(len(_State.requests), 1)

    def test_rejects_path_escape(self):
        transport = HomeAssistantHTTPTransport(self.base_url, "token-a")
        for path in ("api/states", "//evil.example/x", "/../secret", "/api/../secret"):
            with self.subTest(path=path):
                with self.assertRaises(HomeAssistantHTTPError):
                    transport.request("GET", path)

    def test_malformed_and_rate_limit_are_structured_failures(self):
        transport = HomeAssistantHTTPTransport(self.base_url, "token-a")
        _State.mode = "malformed"
        with self.assertRaisesRegex(HomeAssistantHTTPError, "invalid-json"):
            transport.request("GET", "/api/states/light.office")
        _State.mode = "429"
        with self.assertRaisesRegex(HomeAssistantHTTPError, "rate-limited"):
            transport.request("GET", "/api/states/light.office")

    def test_5xx_is_structured_provider_error(self):
        transport = HomeAssistantHTTPTransport(self.base_url, "token-a")
        _State.mode = "503"
        with self.assertRaisesRegex(HomeAssistantHTTPError, "provider-error") as caught:
            transport.request("GET", "/api/states/light.office")
        self.assertNotIn("token-a", str(caught.exception))

    def test_timeout_is_structured_provider_unavailable(self):
        transport = HomeAssistantHTTPTransport(self.base_url, "token-a", timeout=0.05)
        _State.mode = "timeout"
        with self.assertRaisesRegex(HomeAssistantHTTPError, "provider-unavailable") as caught:
            transport.request("GET", "/api/states/light.office")
        self.assertNotIn("token-a", str(caught.exception))

    def test_disconnect_is_structured_provider_unavailable(self):
        transport = HomeAssistantHTTPTransport(self.base_url, "token-a")
        _State.mode = "disconnect"
        with self.assertRaisesRegex(HomeAssistantHTTPError, "provider-unavailable") as caught:
            transport.request("GET", "/api/states/light.office")
        self.assertNotIn("token-a", str(caught.exception))

    def test_base_url_is_confined(self):
        for url in (
            "ftp://127.0.0.1:8123",
            "http://user:pass@127.0.0.1:8123",
            "http://127.0.0.1:8123/base?token=x",
        ):
            with self.subTest(url=url):
                with self.assertRaises(HomeAssistantHTTPError):
                    HomeAssistantHTTPTransport(url, "token-a")


if __name__ == "__main__":
    unittest.main()
