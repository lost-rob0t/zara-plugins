from __future__ import annotations

import logging
import queue

from .bot import ZaraDiscordBot as DiscordClient
from .config import PolicyStore, config_directory, load_token
from .controller import ConversationController


logger = logging.getLogger(__name__)


class ZaraDiscordPlugin:
    def __init__(self) -> None:
        self._bot = None
        self._subscription = None

    def start(self, runtime) -> None:
        directory = config_directory()
        token = load_token(directory)
        policies = PolicyStore(directory)
        controller = ConversationController(runtime)
        self._subscription = runtime.subscribe(maxsize=128)
        self._bot = DiscordClient(controller, policies)

        def consume_events(stop_event) -> None:
            while not stop_event.is_set():
                try:
                    envelope = self._subscription.get(timeout=0.25)
                except queue.Empty:
                    continue
                except RuntimeError:
                    return
                controller.handle_event(envelope.event)

        runtime.start_worker("runtime-events", consume_events)
        runtime.start_worker(
            "gateway",
            lambda stop_event: self._bot.run_gateway(token, stop_event),
        )

    def stop(self) -> None:
        if self._bot is not None:
            self._bot.request_close()
        if self._subscription is not None:
            self._subscription.close()


def create_plugin():
    from zara.plugins import PluginMetadata, ServicePlugin

    metadata = PluginMetadata(
        name="zara-discord",
        version="0.1.0",
        api_version="1",
        description="Talk to Zara through Discord with guild access controls.",
    )

    class ZaraDiscordService(ZaraDiscordPlugin, ServicePlugin):
        pass

    ZaraDiscordService.metadata = metadata
    return ZaraDiscordService()
