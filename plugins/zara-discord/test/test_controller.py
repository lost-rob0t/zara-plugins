import concurrent.futures
import unittest

from discord_test_support import CommandReceipt, install_zara_stubs

install_zara_stubs()

from zara.runtime import events
from zara_discord_service.controller import ConversationController, ConversationHistory


class FakeRuntime:
    def __init__(self, *, raises=False):
        self.commands = []
        self.futures = []
        self.raises = raises

    def dispatch(self, command):
        if self.raises:
            raise RuntimeError("runtime unavailable")
        future = concurrent.futures.Future()
        self.commands.append(command)
        self.futures.append(future)
        return future


class ControllerTests(unittest.TestCase):
    def test_submits_correlated_turn_and_delivers_response(self):
        runtime = FakeRuntime()
        controller = ConversationController(runtime)
        responses = []
        errors = []

        controller.submit(
            text="hello Zara",
            conversation_id="discord:10:30",
            speaker="Mina",
            on_response=responses.append,
            on_error=errors.append,
        )
        command = runtime.commands[0]
        self.assertEqual(command.text, "hello Zara")
        self.assertEqual(command.conversation_id, "discord:10:30")
        runtime.futures[0].set_result(CommandReceipt(command.request_id, "turn-1"))
        controller.handle_event(
            events.ResponseText(
                turn_id="turn-1",
                conversation_id="discord:10:30",
                text="Hi from Zara",
            )
        )

        self.assertEqual(responses, ["Hi from Zara"])
        self.assertEqual(errors, [])

    def test_next_turn_receives_recent_discord_history(self):
        runtime = FakeRuntime()
        controller = ConversationController(runtime, context_budget_chars=512)

        controller.submit(
            text="Import the VRM from Downloads and let me see it.",
            conversation_id="discord:10:30",
            speaker="Mina",
            on_response=lambda _text: None,
            on_error=lambda _text: None,
        )
        first = runtime.commands[0]
        runtime.futures[0].set_result(CommandReceipt(first.request_id, "turn-1"))
        controller.handle_event(
            events.ResponseText(
                turn_id="turn-1",
                conversation_id="discord:10:30",
                text="I got stuck in a tool loop and had to stop.",
            )
        )

        controller.submit(
            text="Retry",
            conversation_id="discord:10:30",
            speaker="Mina",
            on_response=lambda _text: None,
            on_error=lambda _text: None,
        )
        second = runtime.commands[1].text

        self.assertIn("Recent Discord conversation", second)
        self.assertIn("Mina: Import the VRM from Downloads and let me see it.", second)
        self.assertIn("Zara: I got stuck in a tool loop and had to stop.", second)
        self.assertIn("CURRENT Discord message", second)
        self.assertTrue(second.endswith("Mina: Retry"))

    def test_history_budget_is_bounded_and_prefers_recent_entries(self):
        history = ConversationHistory(48)
        history.append("discord:10:30", "Mina", "old-" * 20)
        history.append("discord:10:30", "Zara", "latest answer")

        context = history.context("discord:10:30")

        self.assertLessEqual(len(context), 48)
        self.assertIn("Zara: latest answer", context)

    def test_history_isolated_per_conversation(self):
        runtime = FakeRuntime()
        controller = ConversationController(runtime, context_budget_chars=512)

        controller.submit(
            text="secret first channel context",
            conversation_id="discord:10:30",
            speaker="Mina",
            on_response=lambda _text: None,
            on_error=lambda _text: None,
        )
        first = runtime.commands[0]
        runtime.futures[0].set_result(CommandReceipt(first.request_id, "turn-1"))
        controller.handle_event(
            events.ResponseText(turn_id="turn-1", text="first channel answer")
        )

        controller.submit(
            text="hello",
            conversation_id="discord:10:31",
            speaker="Mina",
            on_response=lambda _text: None,
            on_error=lambda _text: None,
        )

        self.assertEqual(runtime.commands[1].text, "hello")

    def test_zero_history_budget_disables_context_injection(self):
        runtime = FakeRuntime()
        controller = ConversationController(runtime, context_budget_chars=0)

        controller.submit(
            text="first",
            conversation_id="discord:10:30",
            on_response=lambda _text: None,
            on_error=lambda _text: None,
        )
        first = runtime.commands[0]
        runtime.futures[0].set_result(CommandReceipt(first.request_id, "turn-1"))
        controller.handle_event(events.ResponseText(turn_id="turn-1", text="answer"))
        controller.submit(
            text="Retry",
            conversation_id="discord:10:30",
            on_response=lambda _text: None,
            on_error=lambda _text: None,
        )

        self.assertEqual(runtime.commands[1].text, "Retry")

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
        runtime.futures[0].set_exception(RuntimeError("provider secret details"))

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
        runtime.futures[0].set_result(CommandReceipt("request", "turn-1"))
        controller.handle_event(events.AgentFailed(turn_id="turn-1", reason="offline"))

        self.assertEqual(errors, ["Zara could not answer: offline"])

    def test_ignores_unrelated_events_and_empty_turn_ids(self):
        controller = ConversationController(FakeRuntime())

        self.assertFalse(controller.handle_event(events.RuntimeIdle()))
        self.assertFalse(controller.handle_event(events.ResponseText(text="orphan")))


if __name__ == "__main__":
    unittest.main()
