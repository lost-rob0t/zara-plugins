import io
import json
import sys
import unittest
import urllib.error
from pathlib import Path
from urllib.parse import parse_qs, urlsplit


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

from zara_starintel_server.client import StarIntelClient, StarIntelError
from zara_starintel_server.config import StarIntelConfig


class FakeResponse:
    def __init__(
        self,
        payload,
        *,
        status=200,
        headers=None,
        raw=False,
    ):
        self.data = payload if raw else json.dumps(payload).encode("utf-8")
        self.status = status
        self.headers = headers or {"Content-Type": "application/json"}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self, limit=-1):
        return self.data if limit < 0 else self.data[:limit]


class RecordingOpener:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.requests = []
        self.timeouts = []

    def __call__(self, request, timeout):
        self.requests.append(request)
        self.timeouts.append(timeout)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class StarIntelClientTest(unittest.TestCase):
    def config(self, **changes):
        values = {
            "base_url": "https://starintel.example",
            "api_key": "api-secret",
            "bootstrap_secret": "bootstrap-secret",
            "timeout_seconds": 12.0,
            "max_request_bytes": 4096,
            "max_response_bytes": 8192,
        }
        values.update(changes)
        return StarIntelConfig(**values)

    def test_request_sends_bearer_json_query_and_custom_header(self):
        opener = RecordingOpener(
            FakeResponse(
                {"ok": True},
                status=201,
                headers={
                    "Content-Type": "application/json",
                    "X-Correlation-ID": "corr-1",
                },
            )
        )
        client = StarIntelClient(self.config(), opener=opener)

        result = client.request(
            "POST",
            "/new/document/person",
            query={"tenant": "alpha", "tag": ["one", "two"]},
            body={"dtype": "person", "name": "Ada"},
            headers={"Idempotency-Key": "request-1"},
        )

        request = opener.requests[0]
        parsed = urlsplit(request.full_url)
        self.assertEqual(request.method, "POST")
        self.assertEqual(parsed.path, "/new/document/person")
        self.assertEqual(
            parse_qs(parsed.query),
            {"tenant": ["alpha"], "tag": ["one", "two"]},
        )
        self.assertEqual(request.get_header("Authorization"), "Bearer api-secret")
        self.assertEqual(request.get_header("Idempotency-key"), "request-1")
        self.assertEqual(
            json.loads(request.data.decode("utf-8")),
            {"dtype": "person", "name": "Ada"},
        )
        self.assertEqual(result["status"], 201)
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], {"ok": True})
        self.assertEqual(result["correlation_id"], "corr-1")
        self.assertEqual(opener.timeouts, [12.0])

    def test_bootstrap_secret_is_only_sent_to_bootstrap_route(self):
        opener = RecordingOpener(FakeResponse({}), FakeResponse({}))
        client = StarIntelClient(self.config(), opener=opener)

        client.request("GET", "/health")
        client.request("POST", "/auth/bootstrap", body={"owner": "operator"})

        self.assertIsNone(
            opener.requests[0].get_header("X-star-bootstrap-secret")
        )
        self.assertEqual(
            opener.requests[1].get_header("X-star-bootstrap-secret"),
            "bootstrap-secret",
        )

    def test_disabled_client_fails_before_transport(self):
        opener = RecordingOpener(FakeResponse({}))
        client = StarIntelClient(
            self.config(enabled=False),
            opener=opener,
        )
        with self.assertRaisesRegex(StarIntelError, "disabled"):
            client.request("GET", "/health")
        self.assertEqual(opener.requests, [])

    def test_methods_and_paths_are_bounded_to_server_origin(self):
        client = StarIntelClient(self.config(), opener=RecordingOpener())
        for method in ("CONNECT", "TRACE"):
            with self.subTest(method=method):
                with self.assertRaisesRegex(StarIntelError, "method"):
                    client.request(method, "/health")
        for path in ("relative", "//evil.example/path", "https://evil.example/path", "/bad\npath"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(StarIntelError, "path"):
                    client.request("GET", path)

    def test_sensitive_transport_headers_cannot_be_overridden(self):
        client = StarIntelClient(self.config(), opener=RecordingOpener())
        for header in (
            "Authorization",
            "Host",
            "Cookie",
            "Proxy-Authorization",
            "X-Star-Bootstrap-Secret",
        ):
            with self.subTest(header=header):
                with self.assertRaisesRegex(StarIntelError, "header"):
                    client.request("GET", "/health", headers={header: "override"})

    def test_request_and_response_limits_are_enforced(self):
        client = StarIntelClient(
            self.config(max_request_bytes=8),
            opener=RecordingOpener(FakeResponse({})),
        )
        with self.assertRaisesRegex(StarIntelError, "request body"):
            client.request("POST", "/documents/bulk", body={"too": "large"})

        client = StarIntelClient(
            self.config(max_response_bytes=1024),
            opener=RecordingOpener(
                FakeResponse(b"x" * 1025, raw=True, headers={"Content-Type": "text/plain"})
            ),
        )
        with self.assertRaisesRegex(StarIntelError, "response exceeded"):
            client.request("GET", "/health")

    def test_http_errors_return_structured_api_result(self):
        error = urllib.error.HTTPError(
            "https://starintel.example/auth/context",
            403,
            "Forbidden",
            {"Content-Type": "application/json", "X-Correlation-ID": "corr-2"},
            io.BytesIO(b'{"status":"error","code":"forbidden"}'),
        )
        client = StarIntelClient(
            self.config(),
            opener=RecordingOpener(error),
        )

        result = client.request("GET", "/auth/context")

        self.assertFalse(result["ok"])
        self.assertEqual(result["status"], 403)
        self.assertEqual(result["data"]["code"], "forbidden")
        self.assertEqual(result["correlation_id"], "corr-2")

    def test_capabilities_validate_advertised_endpoints(self):
        opener = RecordingOpener(
            FakeResponse(
                {
                    "status": "ok",
                    "data": {
                        "features": {"documents": True},
                        "endpoints": [{"id": "document_read", "method": "GET"}],
                    },
                }
            )
        )
        client = StarIntelClient(self.config(), opener=opener)

        capabilities = client.capabilities()

        self.assertEqual(capabilities["features"], {"documents": True})
        self.assertEqual(capabilities["endpoints"][0]["id"], "document_read")

    def test_invalid_capabilities_fail_closed(self):
        client = StarIntelClient(
            self.config(),
            opener=RecordingOpener(FakeResponse({"status": "ok", "data": {}})),
        )
        with self.assertRaisesRegex(StarIntelError, "endpoints"):
            client.capabilities()

    def test_call_operation_uses_live_manifest_and_escapes_path_values(self):
        manifest = {
            "schema": "starintel-client-manifest-v1",
            "operations": [
                {
                    "operation_id": "auth.users.password.reset",
                    "method": "post",
                    "path": "/auth/users/:username/password",
                    "path_parameters": ["username"],
                }
            ],
        }
        opener = RecordingOpener(FakeResponse(manifest), FakeResponse({"status": "ok"}))
        client = StarIntelClient(self.config(), opener=opener)

        result = client.call_operation(
            "auth.users.password.reset",
            path_parameters={"username": "a/b"},
            body={"password": "replacement"},
        )

        self.assertEqual(
            urlsplit(opener.requests[1].full_url).path,
            "/auth/users/a%2Fb/password",
        )
        self.assertEqual(result["data"], {"status": "ok"})

    def test_call_operation_rejects_unknown_and_missing_parameters(self):
        manifest = {
            "schema": "starintel-client-manifest-v1",
            "operations": [
                {
                    "operation_id": "document.get",
                    "method": "get",
                    "path": "/document/:id",
                    "path_parameters": ["id"],
                }
            ],
        }
        client = StarIntelClient(
            self.config(),
            opener=RecordingOpener(FakeResponse(manifest)),
        )

        with self.assertRaisesRegex(StarIntelError, "missing path parameter"):
            client.call_operation("document.get")
        with self.assertRaisesRegex(StarIntelError, "unknown operation"):
            client.call_operation("missing.operation")


if __name__ == "__main__":
    unittest.main()
