import json
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "lib"))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from zara_home.home_assistant_events import HomeAssistantEventError, HomeAssistantEventStream


class FakeSocket:
    def __init__(self, incoming):
        self.incoming = list(incoming)
        self.sent = []
        self.closed = False

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


class HomeAssistantEventStreamTest(unittest.TestCase):
    TOKEN = "test-token-do-not-log"

    @staticmethod
    def state(entity_id, state, updated, changed=None):
        return {
            "entity_id": entity_id,
            "state": state,
            "attributes": {},
            "last_updated": updated,
            "last_changed": changed or updated,
        }

    def stream(self, sockets, reconciled=None):
        sockets = list(sockets)
        reconciled = reconciled or []
        calls = []

        def connect(url):
            calls.append(url)
            if not sockets:
                raise EOFError("no socket")
            return sockets.pop(0)

        def reconcile():
            return list(reconciled)

        stream = HomeAssistantEventStream(
            "https://ha.example",
            self.TOKEN,
            connect=connect,
            reconcile=reconcile,
            max_frame_bytes=2048,
        )
        return stream, calls

    def test_auth_then_subscription_ack_required_before_events_apply(self):
        sock = FakeSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok", "ha_version": "2026.9"}),
            json.dumps({"id": 1, "type": "event", "event": {"event_type": "state_changed", "data": {"entity_id": "light.desk", "new_state": self.state("light.desk", "on", "2026-09-07T12:00:00+00:00")}}}),
            json.dumps({"id": 1, "type": "result", "success": True, "result": None}),
            json.dumps({"id": 1, "type": "event", "event": {"event_type": "state_changed", "data": {"entity_id": "light.desk", "new_state": self.state("light.desk", "on", "2026-09-07T12:00:01+00:00")}}}),
        ])
        stream, calls = self.stream([sock])
        stream.connect_once()
        self.assertEqual(calls, ["wss://ha.example/api/websocket"])
        self.assertEqual(sock.sent[0], {"type": "auth", "access_token": self.TOKEN})
        self.assertEqual(sock.sent[1], {"id": 1, "type": "subscribe_events", "event_type": "state_changed"})
        self.assertIsNone(stream.observation("light.desk"))
        stream.poll_once()
        self.assertFalse(stream.fresh)
        self.assertIsNone(stream.observation("light.desk"))
        stream.poll_once()
        self.assertTrue(stream.fresh)
        stream.poll_once()
        self.assertTrue(stream.observation("light.desk")["state"]["power"])

    def test_auth_invalid_is_secret_safe(self):
        sock = FakeSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_invalid", "message": self.TOKEN}),
        ])
        stream, _ = self.stream([sock])
        with self.assertRaises(HomeAssistantEventError) as raised:
            stream.connect_once()
        self.assertEqual(str(raised.exception), "reauth-required")
        self.assertNotIn(self.TOKEN, str(raised.exception))

    def test_oversized_or_malformed_frames_do_not_poison_cache(self):
        sock = FakeSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True}),
            "{" + ("x" * 4096),
        ])
        stream, _ = self.stream([sock])
        stream.connect_once()
        stream.poll_once()
        with self.assertRaises(HomeAssistantEventError) as raised:
            stream.poll_once()
        self.assertEqual(str(raised.exception), "frame-too-large")
        self.assertEqual(stream.observations(), {})
        self.assertFalse(stream.fresh)

    def test_unsupported_domain_and_unrelated_ids_are_ignored(self):
        sock = FakeSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True}),
            json.dumps({"id": 99, "type": "event", "event": {"event_type": "state_changed", "data": {"entity_id": "light.desk", "new_state": self.state("light.desk", "on", "2026-09-07T12:00:00+00:00")}}}),
            json.dumps({"id": 1, "type": "event", "event": {"event_type": "state_changed", "data": {"entity_id": "sensor.temp", "new_state": self.state("sensor.temp", "9", "2026-09-07T12:00:01+00:00")}}}),
        ])
        stream, _ = self.stream([sock])
        stream.connect_once()
        stream.poll_once()
        stream.poll_once()
        stream.poll_once()
        self.assertEqual(stream.observations(), {})

    def test_older_last_updated_cannot_replace_newer_observation(self):
        sock = FakeSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True}),
            json.dumps({"id": 1, "type": "event", "event": {"event_type": "state_changed", "data": {"entity_id": "switch.fan", "new_state": self.state("switch.fan", "on", "2026-09-07T12:00:02+00:00")}}}),
            json.dumps({"id": 1, "type": "event", "event": {"event_type": "state_changed", "data": {"entity_id": "switch.fan", "new_state": self.state("switch.fan", "off", "2026-09-07T12:00:01+00:00")}}}),
        ])
        stream, _ = self.stream([sock])
        stream.connect_once()
        stream.poll_once()
        stream.poll_once()
        stream.poll_once()
        self.assertTrue(stream.observation("switch.fan")["state"]["power"])

    def test_reconnect_uses_fresh_subscription_and_reconciles_before_fresh(self):
        first = FakeSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True}),
        ])
        second = FakeSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 2, "type": "result", "success": True}),
        ])
        reconciled = [self.state("light.desk", "off", "2026-09-07T12:05:00+00:00")]
        stream, _ = self.stream([first, second], reconciled)
        stream.connect_once()
        self.assertFalse(stream.fresh)
        stream.poll_once()
        self.assertTrue(stream.fresh)
        stream.mark_disconnected()
        self.assertFalse(stream.fresh)
        stream.connect_once()
        self.assertEqual(second.sent[1]["id"], 2)
        self.assertFalse(stream.fresh)
        stream.poll_once()
        self.assertTrue(stream.fresh)
        self.assertFalse(stream.observation("light.desk")["state"]["power"])

    def test_stop_closes_socket_and_prevents_reconnect(self):
        sock = FakeSocket([
            json.dumps({"type": "auth_required"}),
            json.dumps({"type": "auth_ok"}),
            json.dumps({"id": 1, "type": "result", "success": True}),
        ])
        stream, _ = self.stream([sock])
        stream.connect_once()
        stream.stop()
        self.assertTrue(sock.closed)
        with self.assertRaises(HomeAssistantEventError) as raised:
            stream.connect_once()
        self.assertEqual(str(raised.exception), "stopped")


if __name__ == "__main__":
    unittest.main()
