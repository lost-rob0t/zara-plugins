from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from zara.runtime import events
from zara.runtime.commands import ApproveTool, SubmitTurn

from .routing import ResponseRouter


@dataclass(frozen=True)
class TurnOutcome:
    success: bool
    message: str


class ConversationController:
    def __init__(self, runtime, *, auto_approve_tools: bool = True) -> None:
        self._runtime = runtime
        self._auto_approve_tools = bool(auto_approve_tools)
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
        if isinstance(event, events.ToolWaitingForUser):
            return self._handle_tool_wait(event)
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

    def _handle_tool_wait(self, event) -> bool:
        conversation_id = getattr(event, "conversation_id", None)
        tool_run_id = getattr(event, "tool_run_id", None)
        if not self._auto_approve_tools:
            return False
        if not conversation_id or not str(conversation_id).startswith("discord:"):
            return False
        if not tool_run_id:
            return False

        try:
            future = self._runtime.dispatch(ApproveTool(tool_run_id=tool_run_id))
        except Exception:
            self._router.deliver(
                event.turn_id,
                TurnOutcome(False, "Zara could not approve that tool call."),
            )
            return True

        def approved(completed) -> None:
            try:
                completed.result()
            except Exception:
                self._router.deliver(
                    event.turn_id,
                    TurnOutcome(False, "Zara could not approve that tool call."),
                )

        future.add_done_callback(approved)
        return True
