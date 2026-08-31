from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from zara.runtime import events
from zara.runtime.commands import SubmitTurn

from .routing import ResponseRouter


@dataclass(frozen=True)
class TurnOutcome:
    success: bool
    message: str


class ConversationController:
    def __init__(self, runtime) -> None:
        self._runtime = runtime
        self._router: ResponseRouter[TurnOutcome] = ResponseRouter()

    def submit(
        self,
        *,
        text: str,
        conversation_id: str,
        on_response: Callable[[str], None],
        on_error: Callable[[str], None],
    ) -> None:
        try:
            future = self._runtime.dispatch(
                SubmitTurn(text=text, conversation_id=conversation_id)
            )
        except Exception:
            on_error("Zara could not accept that message.")
            return

        def accepted(completed) -> None:
            try:
                receipt = completed.result()
                if not receipt.turn_id:
                    raise RuntimeError("Zara did not assign a turn id")
            except Exception:
                on_error("Zara could not accept that message.")
                return

            def deliver(outcome: TurnOutcome) -> None:
                if outcome.success:
                    on_response(outcome.message)
                else:
                    on_error(outcome.message)

            self._router.register(receipt.turn_id, deliver)

        future.add_done_callback(accepted)

    def handle_event(self, event) -> bool:
        if not event.turn_id:
            return False
        if isinstance(event, events.ResponseText):
            self._router.deliver(event.turn_id, TurnOutcome(True, event.text))
            return True
        if isinstance(event, (events.AgentFailed, events.AssistantFailed)):
            reason = event.reason or "the runtime failed"
            self._router.deliver(
                event.turn_id,
                TurnOutcome(False, f"Zara could not answer: {reason}"),
            )
            return True
        if isinstance(event, events.TurnCancelled):
            reason = event.reason or "the turn was cancelled"
            self._router.deliver(
                event.turn_id,
                TurnOutcome(False, f"Zara could not answer: {reason}"),
            )
            return True
        return False
