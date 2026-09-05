from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import ContactsDomain, ContactsError


PLUGIN_VERSION = "0.1.0"


class UnavailableContactsBackend:
    reason = "contacts-backend-not-configured"

    def __getattr__(self, name):
        raise ContactsError(self.reason)


class ZaraContactsPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-contacts",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Normalized contact identity and ambiguity-safe recipient resolution",
    )

    def __init__(self, backend=None) -> None:
        self.backend = backend or UnavailableContactsBackend()
        self.domain = ContactsDomain(self.backend)

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if isinstance(self.backend, UnavailableContactsBackend):
            return self._json({"status": "unavailable", "reason": self.backend.reason})
        return self._json({"status": "ready"})

    def search(self, query: str, limit: int = 50) -> str:
        return self._json(self.domain.search(query, limit=limit))

    def get(self, contact_id: str) -> str:
        return self._json(self.domain.get(contact_id))

    def resolve(self, query: str, channel: str) -> str:
        return self._json(self.domain.resolve(query, channel=channel))

    def create(
        self,
        display_name: str,
        aliases: list[str],
        emails: list[str],
        phones: list[str],
        organizations: list[dict],
        handles: list[dict],
        sources: list[dict],
    ) -> str:
        return self._json(
            self.domain.create(
                {
                    "display_name": display_name,
                    "aliases": aliases,
                    "emails": emails,
                    "phones": phones,
                    "organizations": organizations,
                    "handles": handles,
                    "sources": sources,
                }
            )
        )

    def update(self, contact_id: str, patch: dict) -> str:
        return self._json(self.domain.update(contact_id, patch))

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="contacts.status", description="Report contact-provider availability."),
            StructuredTool.from_function(func=self.search, name="contacts.search", description="Search bounded normalized contacts by name, alias, address, or organization."),
            StructuredTool.from_function(func=self.get, name="contacts.get", description="Read one normalized contact by stable ID."),
            StructuredTool.from_function(func=self.resolve, name="contacts.resolve", description="Resolve a recipient for an explicit channel without guessing ambiguous identities."),
            StructuredTool.from_function(func=self.create, name="contacts.create", description="Create an explicit normalized contact and verify observed provider state."),
            StructuredTool.from_function(func=self.update, name="contacts.update", description="Update explicit contact fields and verify observed provider state."),
        )


def create_plugin():
    return ZaraContactsPlugin()
