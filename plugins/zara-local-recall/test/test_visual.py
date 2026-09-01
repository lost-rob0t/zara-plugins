"""Deterministic tests for the visual-context protocol client."""

import json
import unittest

from local_recall_test_support import LIB_ROOT  # noqa: F401

from zara_local_recall_service import visual


class RequestFrameTests(unittest.TestCase):
    def test_frames_carry_protocol_and_bounds(self) -> None:
        frames = visual.build_request(
            selector="recent",
            maximum_records=3,
            request_id="ab" * 8,
        )
        self.assertEqual(len(frames), 2)
        routing = json.loads(frames[0])
        payload = json.loads(frames[1])
        self.assertEqual(routing["visual_context_version"], "zara-visual-context-v1")
        self.assertEqual(routing["remote_authorization"], "absent")
        self.assertEqual(payload["selector"], "recent")
        self.assertEqual(payload["maximum_records"], 3)
        self.assertIsNone(payload["start"])
        self.assertIsNone(payload["end"])

    def test_invalid_selector_is_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            visual.build_request(selector="everything", maximum_records=3, request_id="ab" * 8)

    def test_invalid_record_budget_is_rejected(self) -> None:
        with self.assertRaises(RuntimeError):
            visual.build_request(selector="recent", maximum_records=99, request_id="ab" * 8)


class ResponseParsingTests(unittest.TestCase):
    def test_explained_response_is_parsed(self) -> None:
        document = {
            "protocol_version": "zara-visual-context-v1",
            "request_id": "ab" * 8,
            "outcome": "explained",
            "explanation": "editing: emacs with a document open",
            "record_count": 2,
            "provider_class": "local",
            "reason_code": None,
        }
        answer = visual.parse_response(
            json.dumps(document).encode("utf-8"), request_id="ab" * 8
        )
        self.assertEqual(answer.outcome, "explained")
        self.assertEqual(answer.record_count, 2)
        self.assertEqual(answer.provider_class, "local")

    def test_denied_response_carries_reason_only(self) -> None:
        document = {
            "protocol_version": "zara-visual-context-v1",
            "request_id": "ab" * 8,
            "outcome": "denied",
            "reason_code": "privacy-mode",
        }
        answer = visual.parse_response(
            json.dumps(document).encode("utf-8"), request_id="ab" * 8
        )
        self.assertEqual(answer.outcome, "denied")
        self.assertEqual(answer.reason_code, "privacy-mode")
        self.assertEqual(answer.explanation, "")

    def test_version_mismatch_is_rejected(self) -> None:
        document = {
            "protocol_version": "zara-visual-context-v0",
            "request_id": "ab" * 8,
            "outcome": "denied",
            "reason_code": "x",
        }
        with self.assertRaises(RuntimeError):
            visual.parse_response(json.dumps(document).encode("utf-8"), request_id="ab" * 8)

    def test_request_id_mismatch_is_rejected(self) -> None:
        document = {
            "protocol_version": "zara-visual-context-v1",
            "request_id": "cd" * 8,
            "outcome": "denied",
            "reason_code": "x",
        }
        with self.assertRaises(RuntimeError):
            visual.parse_response(json.dumps(document).encode("utf-8"), request_id="ab" * 8)


class ExchangeTests(unittest.TestCase):
    def test_transport_receives_three_frames_with_token(self) -> None:
        seen: list[list[bytes]] = []

        def send(frames: list[bytes], timeout: float) -> bytes:
            seen.append(list(frames))
            self.assertEqual(timeout, 8.0)
            return json.dumps(
                {
                    "protocol_version": "zara-visual-context-v1",
                    "request_id": seen[0] and json.loads(seen[0][0])["request_id"],
                    "outcome": "denied",
                    "reason_code": "missing-context",
                }
            ).encode("utf-8")

        answer = visual.explain_screen(
            selector="recent",
            maximum_records=2,
            timeout_seconds=8.0,
            send=send,
        )
        self.assertEqual(answer.outcome, "denied")
        self.assertEqual(len(seen), 1)

    def test_transport_failure_maps_to_runtime_error(self) -> None:
        def send(frames: list[bytes], timeout: float) -> bytes:
            raise RuntimeError("visual-response-invalid")

        with self.assertRaises(RuntimeError):
            visual.explain_screen(
                selector="recent",
                maximum_records=2,
                timeout_seconds=8.0,
                send=send,
            )


if __name__ == "__main__":
    unittest.main()
