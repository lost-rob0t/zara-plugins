import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lib"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zara_home.home_assistant_events import HomeAssistantEventStream


class FakeSocket:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []
        self.closed = False
        self.timeout = None

    def settimeout(self, value):
        self.timeout = value

    def recv(self):
        if not self.incoming:
            raise EOFError("disconnect")
        item = self.incoming.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def send(self, payload):
        self.sent.append(json.loads(payload))

    def close(self):
        self.closed = True


def handshake(subscription_id):
    return [
        json.dumps({"type": "auth_required"}),
        json.dumps({"type": "auth_ok"}),
        json.dumps({"id": subscription_id, "type": "result", "success": True}),
    ]


class HomeAssistantEventLifecycleTest(unittest.TestCase):
    def make_stream(self, sockets, *, wait=None):
        sockets = list(sockets)
        connects = []

        def connect(url):
            connects.append(url)
            if not sockets:
                raise EOFError("no socket")
            return sockets.pop(0)

        stream = HomeAssistantEventStream(
            "https://ha.example",
            "test-token",
            connect=connect,
            reconcile=lambda: [],
            io_timeout_seconds=3.0,
            reconnect_backoff=(1.0, 2.0),
            wait=wait,
        )
        return stream, connects

    def test_socket_read_timeout_is_bounded_before_auth_recv(self):
        sock = FakeSocket(handshake(1))
        stream, _ = self.make_stream([sock])
        stream.connect_once()
        self.assertEqual(sock.timeout, 3.0)

    def test_run_forever_reconnects_with_bounded_backoff(self):
        first = FakeSocket(handshake(1))
        second = FakeSocket(handshake(2))
        waits = []

        def wait(delay):
            waits.append(delay)
            return len(waits) >= 2

        stream, connects = self.make_stream([first, second], wait=wait)
        stream.run_forever()

        self.assertEqual(len(connects), 2)
        self.assertEqual(waits, [1.0, 2.0])
        self.assertTrue(first.closed)
        self.assertTrue(second.closed)
        self.assertFalse(stream.fresh)

    def test_stop_during_reconnect_wait_cancels_next_connect(self):
        first = FakeSocket(handshake(1))
        holder = {}
        waits = []

        def wait(delay):
            waits.append(delay)
            holder["stream"].stop()
            return True

        stream, connects = self.make_stream([first], wait=wait)
        holder["stream"] = stream
        stream.run_forever()

        self.assertEqual(len(connects), 1)
        self.assertEqual(waits, [1.0])
        self.assertTrue(first.closed)

    def test_backoff_and_timeout_configuration_are_bounded(self):
        with self.assertRaisesRegex(RuntimeError, "invalid-io-timeout"):
            HomeAssistantEventStream(
                "https://ha.example", "test-token", connect=lambda _: None,
                reconcile=lambda: [], io_timeout_seconds=0,
            )
        with self.assertRaisesRegex(RuntimeError, "invalid-reconnect-backoff"):
            HomeAssistantEventStream(
                "https://ha.example", "test-token", connect=lambda _: None,
                reconcile=lambda: [], reconnect_backoff=(0.0,),
            )


if __name__ == "__main__":
    unittest.main()
