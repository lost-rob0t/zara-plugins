import concurrent.futures
import unittest

from discord_test_support import CommandReceipt, install_zara_stubs

install_zara_stubs()

from zara.runtime import events
from zara_discord_service.controller import ConversationController
from zara_discord_service.inspection import NO_REPLY_SENTINEL


class FakeRuntime:
    def __init__(self):
        self.commands = []
        self.futures = []

    def dispatch(self, command):
        future = concurrent.futures.Future()
        self.commands.append(command)
        self.futures.append(future)
        return future


class NoReplySentinelTests(unittest.TestCase):
    def test_suppressed_response_is_not_delivered_or_added_to_history(self):
        runtime = FakeRuntime()
        controller = ConversationController(runtime, context_budget_chars=512)
        responses = []

        controller.submit(
            text="inspect this",
            conversation_id="discord:10:30",
            on_response=responses.append,
            on_error=self.fail,
            suppress_exact=frozenset({NO_REPLY_SENTINEL}),
        )
        first = runtime.commands[0]
        runtime.futures[0].set_result(CommandReceipt(first.request_id, "turn-1"))
        controller.handle_event(
            events.ResponseText(turn_id="turn-1", text=f"  {NO_REPLY_SENTINEL}  ")
        )

        self.assertEqual(responses, [])

        controller.submit(
            text="next",
            conversation_id="discord:10:30",
            on_response=lambda _text: None,
            on_error=self.fail,
        )
        self.assertNotIn(NO_REPLY_SENTINEL, runtime.commands[1].text)


if __name__ == "__main__":
    unittest.main()
