from __future__ import annotations

import json

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import SysadminError, SysadminExpert


PLUGIN_VERSION = "0.1.0"


class UnavailableSystemBackend:
    reason = "system-backend-not-configured"

    def __getattr__(self, name):
        raise SysadminError(self.reason)


class ZaraSysadminPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-sysadmin",
        version=PLUGIN_VERSION,
        api_version="1",
        description="Typed Linux/NixOS diagnostics and verified remediation",
    )

    def __init__(self, backend=None) -> None:
        self.backend = backend or UnavailableSystemBackend()
        self.expert = SysadminExpert(self.backend)

    def start(self, runtime) -> None:
        return None

    def stop(self) -> None:
        return None

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    def status(self) -> str:
        if isinstance(self.backend, UnavailableSystemBackend):
            return self._json({"status": "unavailable", "reason": self.backend.reason})
        return self._json({"status": "ready"})

    def service_status(self, unit: str) -> str:
        return self._json(self.expert.service_status(unit))

    def diagnose_service(self, unit: str) -> str:
        return self._json(self.expert.diagnose_service(unit))

    def diagnose_service_port(self, unit: str, port: int) -> str:
        return self._json(self.expert.diagnose_service_port(unit, port))

    def journal(self, unit: str, limit: int = 50) -> str:
        return self._json(self.expert.journal(unit, limit))

    def processes(self, limit: int = 25) -> str:
        return self._json(self.expert.processes(limit))

    def resources(self) -> str:
        return self._json(self.expert.resources())

    def network(self) -> str:
        return self._json(self.expert.network())

    def diagnose_dns(self) -> str:
        return self._json(self.expert.diagnose_dns())

    def nix_generations(self, limit: int = 20) -> str:
        return self._json(self.expert.nix_generations(limit))

    def service_action(self, unit: str, action: str) -> str:
        return self._json(self.expert.service_action(unit, action))

    def nix_operation(self, operation: str, target: str) -> str:
        return self._json(self.expert.nix_operation(operation, target))

    def rule_inventory(self) -> str:
        return self._json(self.expert.rule_inventory())

    def tools(self):
        return (
            StructuredTool.from_function(func=self.status, name="sysadmin.status", description="Report whether a structured system backend is configured."),
            StructuredTool.from_function(func=self.service_status, name="sysadmin.service.status", description="Read structured service state for one bounded unit name."),
            StructuredTool.from_function(func=self.diagnose_service, name="sysadmin.service.diagnose", description="Derive service hypotheses from structured state and recent bounded journal evidence."),
            StructuredTool.from_function(func=self.diagnose_service_port, name="sysadmin.service.port_diagnose", description="Correlate service activity with one listener port and derive the next diagnostic path."),
            StructuredTool.from_function(func=self.journal, name="sysadmin.journal", description="Read a bounded number of structured recent journal lines for one unit."),
            StructuredTool.from_function(func=self.processes, name="sysadmin.processes", description="Return a bounded structured process summary."),
            StructuredTool.from_function(func=self.resources, name="sysadmin.resources", description="Return structured load, memory, CPU and filesystem observations."),
            StructuredTool.from_function(func=self.network, name="sysadmin.network", description="Return structured interface, route and resolver observations."),
            StructuredTool.from_function(func=self.diagnose_dns, name="sysadmin.dns.diagnose", description="Distinguish resolver, route and upstream DNS failure paths from structured facts."),
            StructuredTool.from_function(func=self.nix_generations, name="sysadmin.nix.generations", description="Return a bounded structured Nix generation summary."),
            StructuredTool.from_function(func=self.service_action, name="sysadmin.service.action", description="Run an allowlisted service start/stop/restart through the configured backend and verify post-change state."),
            StructuredTool.from_function(func=self.nix_operation, name="sysadmin.nix.operation", description="Run an allowlisted Nix check/build/switch through the configured backend and preserve verification evidence."),
            StructuredTool.from_function(func=self.rule_inventory, name="sysadmin.rules", description="Return the typed diagnostic rule inventory and required verification steps."),
        )


def create_plugin():
    return ZaraSysadminPlugin()
