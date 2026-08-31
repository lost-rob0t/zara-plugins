import concurrent.futures
import unittest

from discord_test_support import CommandReceipt, install_zara_stubs

install_zara_stubs()

from zara.runtime import events
from zara_discord_service.controller import ConversationController


class FakeRuntime:
    def __init__(self, *, raises=False):
        self.commands = []
        self.next_future = concurrent.futures.Future()
        self.raises = raises

    def dispatch(self, command):
        if self.raises:
            raise RuntimeError("runtime unavailable")
        self.commands.append(command)
        return self.next_future


class ControllerTests(unittest.TestCase):
    def test_submits_correlated_turn_and_delivers_response(self):
        runtime = FakeRuntime()
        controller = ConversationController(runtime)
        responses = []
        errors = []

        controller.submit(
            text="hello Zara",
            conversation_id="discord:10:30",
            on_response=responses.append,
            on_error=errors.append,
        )
        command = runtime.commands[0]
        self.assertEqual(command.text, "hello Zara")
        self.assertEqual(command.conversation_id, "discord:10:30")
        runtime.next_future.set_result(CommandReceipt(command.request_id, "turn-1"))
        controller.handle_event(
            events.ResponseText(
                turn_id="turn-1",
                conversation_id="discord:10:30",
                text="Hi from Zara",
            )
        )

        self.assertEqual(responses, ["Hi from Zara"])
        self.assertEqual(errors, [])

    def test_reports_async_dispatch_failure_without_exception_details(self):
        runtime = FakeRuntime()
        controller = ConversationController(runtime)
        errors = []
        controller.submit(
            text="hello",
            conversation_id="discord:10:30",
            on_response=lambda _text: None,
            on_error=errors.append,
        )
        runtime.next_future.set_exception(RuntimeError("provider secret details"))

        self.assertEqual(errors, ["Zara could not accept that message."])

    def test_reports_synchronous_dispatch_failure(self):
        controller = ConversationController(FakeRuntime(raises=True))
        errors = []
        controller.submit(
            text="hello",
            conversation_id="discord:10:30",
            on_response=lambda _text: None,
            on_error=errors.append,
        )

        self.assertEqual(errors, ["Zara could not accept that message."])

    def test_routes_failed_and_cancelled_turns(self):
        runtime = FakeRuntime()
        controller = ConversationController(runtime)
        errors = []
        controller.submit(
            text="hello",
            conversation_id="discord:10:30",
            on_response=lambda _text: None,
            on_error=errors.append,
        )
        runtime.next_future.set_result(CommandReceipt("request", "turn-1"))
        controller.handle_event(events.AgentFailed(turn_id="turn-1", reason="offline"))

        self.assertEqual(errors, ["Zara could not answer: offline"])

    def test_ignores_unrelated_events_and_empty_turn_ids(self):
        controller = ConversationController(FakeRuntime())

        self.assertFalse(controller.handle_event(events.RuntimeIdle()))
        self.assertFalse(controller.handle_event(events.ResponseText(text="orphan")))


if __name__ == "__main__":
    unittest.main()
