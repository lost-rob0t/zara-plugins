from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import CommsDomain, CommsError


PLUGIN_VERSION = "0.1.0"


class UnavailableResolver:
    def resolve(self, query, channel):
        raise CommsError("contacts-resolver-not-configured")


class ZaraCommsPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-comms",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Provider-neutral messaging with ambiguity-safe contacts and verified sends",
    )

    def __init__(self, providers=None, resolver=None) -> None:
        self.providers = dict(providers or {})
        self.resolver = resolver or UnavailableResolver()
        self.domain = None if not self.providers else CommsDomain(self.providers, self.resolver)

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _domain(self):
        if self.domain is None:
            raise CommsError("comms-provider-not-configured")
        return self.domain

    def status(self) -> str:
        return self._json({"status": "ready" if self.domain else "unavailable", "providers": sorted(self.providers), "reason": None if self.domain else "comms-provider-not-configured"})

    def search(self, query: str, provider: str = "", limit: int = 50) -> str:
        return self._json(self._domain().search(query, provider=provider or None, limit=limit))

    def get(self, provider: str, message_id: str) -> str:
        return self._json(self._domain().get(provider, message_id))

    def draft(self, provider: str, account_id: str, recipient_query: str, subject: str, body: str) -> str:
        return self._json(self._domain().draft(provider=provider, account_id=account_id, recipient_query=recipient_query, subject=subject, body=body))

    def draft_reply(self, provider: str, message_id: str, body: str) -> str:
        return self._json(self._domain().draft_reply(provider, message_id, body))

    def send(self, draft: dict) -> str:
        return self._json(self._domain().send(draft))

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="comms.status", description="Report configured messaging providers."),
            StructuredTool.from_function(func=self.search, name="comms.search", description="Search bounded normalized messages across configured providers."),
            StructuredTool.from_function(func=self.get, name="comms.get", description="Read one normalized provider message."),
            StructuredTool.from_function(func=self.draft, name="comms.draft", description="Create a non-sending draft after ambiguity-safe contact resolution."),
            StructuredTool.from_function(func=self.draft_reply, name="comms.draft_reply", description="Create a non-sending reply draft preserving provider thread identity."),
            StructuredTool.from_function(func=self.send, name="comms.send", description="Explicitly send a draft and verify provider-observed message state."),
        )


def create_plugin():
    return ZaraCommsPlugin()
