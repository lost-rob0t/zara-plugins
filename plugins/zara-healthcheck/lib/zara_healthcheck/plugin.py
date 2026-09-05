from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import HealthDomain, HealthError


PLUGIN_VERSION = "0.1.0"


class ZaraHealthcheckPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-healthcheck",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Passive bounded health probes with hysteresis, evidence, and structured facts",
    )

    def __init__(self, probes=None, **domain_options):
        self.probes = dict(probes or {})
        self.domain = HealthDomain(self.probes, **domain_options) if self.probes else None

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def _domain(self):
        if self.domain is None:
            raise HealthError("health-probes-not-configured")
        return self.domain

    def status(self) -> str:
        return self._json({
            "status": "ready" if self.domain else "unavailable",
            "probes": sorted(self.probes),
            "reason": None if self.domain else "health-probes-not-configured",
        })

    def poll(self) -> str:
        return self._json(self._domain().poll())

    def state(self) -> str:
        return self._json(self._domain().state())

    def history(self, probe: str) -> str:
        return self._json(self._domain().history(probe))

    def drain_events(self) -> str:
        return self._json(self._domain().drain_events())

    def export_facts(self) -> str:
        return self._json(self._domain().export_facts())

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="health.status", description="Report configured passive health probes."),
            StructuredTool.from_function(func=self.poll, name="health.poll", description="Run one bounded passive health-probe cycle."),
            StructuredTool.from_function(func=self.state, name="health.state", description="Return hysteresis-filtered current health state."),
            StructuredTool.from_function(func=self.history, name="health.history", description="Return bounded observation history for one probe."),
            StructuredTool.from_function(func=self.drain_events, name="health.drain_events", description="Consume deduplicated health state-change events."),
            StructuredTool.from_function(func=self.export_facts, name="health.export_facts", description="Export normalized health facts and evidence for expert consumers."),
        )


def create_plugin():
    return ZaraHealthcheckPlugin()
