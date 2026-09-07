from __future__ import annotations

import logging
import queue

from .config import ConfigError, PolicyStore, config_directory, load_token
from .controller import ConversationController
from .moderation import ModerationContextStore
from .moderation_acknowledgements import ModerationAcknowledgementStore
from .moderation_audit import ModerationAudit
from .moderation_bot import ModeratedZaraDiscordBot as DiscordClient
from .moderation_tools import build_moderation_tools


logger = logging.getLogger(__name__)


def _message_content_enabled(client) -> bool:
    intents = getattr(client, "intents", None)
    return bool(getattr(intents, "message_content", False))


class ZaraDiscordPlugin:
    def __init__(self) -> None:
        self._bot = None
        self._subscription = None
        self._moderation_contexts = ModerationContextStore()

    def tools(self):
        return build_moderation_tools(
            self._moderation_contexts,
            self._execute_moderation,
        )

    def _execute_moderation(self, action, context, reason, timeout_seconds):
        if self._bot is None:
            raise RuntimeError("Discord moderation is unavailable because the plugin is not started")
        return self._bot.execute_moderation(
            action,
            context,
            reason,
            timeout_seconds,
        )

    def start(self, runtime) -> None:
        directory = config_directory()
        try:
            token = load_token(directory)
        except ConfigError:
            # API v1 has no canonical plugin-unavailable lifecycle result. Keep the
            # zero-secret compatibility contract without allocating any runtime
            # resources; Core issue #658 tracks the missing public state seam.
            logger.warning("Discord plugin unavailable: configuration is invalid")
            return

        policies = PolicyStore(directory)
        acknowledgements = ModerationAcknowledgementStore(directory)
        audit = ModerationAudit()
        controller = ConversationController(runtime)
        message_content_requested = policies.requires_message_content()
        bot = DiscordClient(
            controller,
            policies,
            self._moderation_contexts,
            acknowledgements,
            audit,
            message_content=message_content_requested,
        )
        if not _message_content_enabled(bot):
            logger.warning(
                "Discord Message Content intent is disabled; ordinary-message "
                "inspection is metadata-only and must report content_available=false"
            )

        subscription = runtime.subscribe(maxsize=128)
        self._bot = bot
        self._subscription = subscription

        def consume_events(stop_event) -> None:
            while not stop_event.is_set():
                try:
                    envelope = subscription.get(timeout=0.25)
                except queue.Empty:
                    continue
                except RuntimeError:
                    return
                controller.handle_event(envelope.event)

        try:
            runtime.start_worker("runtime-events", consume_events)
            runtime.start_worker(
                "gateway",
                lambda stop_event: bot.run_gateway(token, stop_event),
            )
        except Exception:
            bot.request_close()
            subscription.close()
            self._bot = None
            self._subscription = None
            raise

    def stop(self) -> None:
        if self._bot is not None:
            self._bot.request_close()
        if self._subscription is not None:
            self._subscription.close()
        self._bot = None
        self._subscription = None


def create_plugin():
    from zara.plugins import PluginMetadata, ServicePlugin

    metadata = PluginMetadata(
        name="zara-discord",
        version="0.3.0",
        api_version="1",
        description="Talk to Zara through Discord with access controls and spontaneous random replies",
    )

    class ZaraDiscordService(ZaraDiscordPlugin, ServicePlugin):
        pass

    ZaraDiscordService.metadata = metadata
    return ZaraDiscordService()
