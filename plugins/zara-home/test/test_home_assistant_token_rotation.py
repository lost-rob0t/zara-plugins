import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lib"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zara_home.home_assistant_events import HomeAssistantEventError, HomeAssistantEventStream
from zara_home.home_assistant_transport import HomeAssistantHTTPTransport


class FakeSocket:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []
        self.closed = False

    def recv(self):
        if not self.incoming:
            raise EOFError("disconnect")
        return self.incoming.pop(0)

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def settimeout(self, _timeout):
        pass

    def close(self):
        self.closed = True


class HomeAssistantTokenRotationTest(unittest.TestCase):
    def test_reconnect_auth_uses_transport_token_rotated_after_stream_construction(self):
        old_token = "old-token"
        new_token = "new-token"
        transport = HomeAssistantHTTPTransport("https://ha.example", old_token)
        stream = HomeAssistantEventStream.from_transport(transport)

        first = FakeSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
        ])
        stream._connect = lambda _url: first
        stream.connect_once()
        self.assertEqual(first.sent[0], {"type": "auth", "access_token": old_token})
        stream.mark_disconnected()

        transport._access_token = new_token
        second = FakeSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
        ])
        stream._connect = lambda _url: second
        stream.connect_once()
        self.assertEqual(second.sent[0], {"type": "auth", "access_token": new_token})

    def test_malformed_rotated_transport_token_fails_secret_safe_before_send(self):
        transport = HomeAssistantHTTPTransport("https://ha.example", "valid-token")
        stream = HomeAssistantEventStream.from_transport(transport)
        malformed = "rotated-secret\r\nX-Leak: yes"
        transport._access_token = malformed
        sock = FakeSocket([json.dumps({"type": "auth_required"})])
        stream._connect = lambda _url: sock

        with self.assertRaises(HomeAssistantEventError) as raised:
            stream.connect_once()

        self.assertEqual(str(raised.exception), "reauth-required")
        self.assertNotIn(malformed, str(raised.exception))
        self.assertEqual(sock.sent, [])
        self.assertTrue(sock.closed)


if __name__ == "__main__":
    unittest.main()
