from __future__ import annotations

from collections import OrderedDict, deque
from dataclasses import dataclass
import threading
from typing import Callable

from zara.runtime import events
from zara.runtime.commands import SubmitTurn

from .privacy import filter_public_output
from .routing import ResponseRouter


DEFAULT_CONTEXT_BUDGET_CHARS = 12_000
MAX_HISTORY_CONVERSATIONS = 256


@dataclass(frozen=True)
class TurnOutcome:
    success: bool
    message: str


class ConversationHistory:
    def __init__(
        self,
        budget_chars: int = DEFAULT_CONTEXT_BUDGET_CHARS,
        *,
        max_conversations: int = MAX_HISTORY_CONVERSATIONS,
    ) -> None:
        self._budget_chars = max(0, int(budget_chars))
        self._max_conversations = max(1, int(max_conversations))
        self._entries: OrderedDict[str, deque[str]] = OrderedDict()
        self._lock = threading.RLock()

    def append(self, conversation_id: str, speaker: str, text: str) -> None:
        if self._budget_chars == 0:
            return
        rendered = self._render_entry(speaker, text)
        if not rendered:
            return
        rendered = self._clip(rendered)

        with self._lock:
            entries = self._entries.pop(conversation_id, deque())
            entries.append(rendered)
            while entries and len("\n".join(entries)) > self._budget_chars:
                entries.popleft()
            if entries:
                self._entries[conversation_id] = entries
            while len(self._entries) > self._max_conversations:
                self._entries.popitem(last=False)

    def context(self, conversation_id: str) -> str:
        if self._budget_chars == 0:
            return ""
        with self._lock:
            entries = self._entries.get(conversation_id)
            if not entries:
                return ""
            self._entries.move_to_end(conversation_id)
            return "\n".join(entries)

    def render(self, conversation_id: str, speaker: str, text: str) -> str:
        context = self.context(conversation_id)
        if not context:
            return text
        current = self._render_entry(speaker, text)
        return (
            "Recent Discord conversation (oldest to newest, bounded by the configured "
            "context budget). Use it as context and answer the CURRENT Discord message.\n"
            "HISTORY:\n"
            f"{context}\n\n"
            "CURRENT Discord message:\n"
            f"{current}"
        )

    def _clip(self, text: str) -> str:
        if len(text) <= self._budget_chars:
            return text
        if self._budget_chars <= 3:
            return text[: self._budget_chars]
        available = self._budget_chars - 1
        head = available // 2
        tail = available - head
        return f"{text[:head]}…{text[-tail:]}"

    @staticmethod
    def _render_entry(speaker: str, text: str) -> str:
        name = " ".join(str(speaker or "User").split())[:80] or "User"
        body = str(text).strip()
        if not body:
            return ""
        return f"{name}: {body}"


class ConversationController:
    def __init__(
        self,
        runtime,
        *,
        context_budget_chars: int = DEFAULT_CONTEXT_BUDGET_CHARS,
    ) -> None:
        self._runtime = runtime
        self._router: ResponseRouter[TurnOutcome] = ResponseRouter()
        self._history = ConversationHistory(context_budget_chars)

    def submit(
        self,
        *,
        text: str,
        conversation_id: str,
        on_response: Callable[[str], None],
        on_error: Callable[[str], None],
        speaker: str = "User",
        suppress_exact: frozenset[str] = frozenset(),
    ) -> None:
        submitted_text = self._history.render(conversation_id, speaker, text)
        self._history.append(conversation_id, speaker, text)
        try:
            future = self._runtime.dispatch(
                SubmitTurn(text=submitted_text, conversation_id=conversation_id)
            )
        except Exception:
            message = "Zara could not accept that message."
            self._history.append(conversation_id, "Zara", message)
            on_error(message)
            return

        suppressed = frozenset(str(item).strip() for item in suppress_exact)

        def accepted(completed) -> None:
            try:
                receipt = completed.result()
                if not receipt.turn_id:
                    raise RuntimeError("Zara did not assign a turn id")
            except Exception:
                message = "Zara could not accept that message."
                self._history.append(conversation_id, "Zara", message)
                on_error(message)
                return

            def deliver(outcome: TurnOutcome) -> None:
                raw = str(outcome.message or "").strip()
                if outcome.success and raw in suppressed:
                    return
                public = filter_public_output(outcome.message)
                self._history.append(conversation_id, "Zara", public.text)
                if outcome.success:
                    on_response(public.text)
                else:
                    on_error(public.text)

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
