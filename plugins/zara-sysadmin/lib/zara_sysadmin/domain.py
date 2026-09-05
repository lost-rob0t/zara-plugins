from __future__ import annotations


class SysadminError(RuntimeError):
    pass


_RULES = {
    "service_failed": {
        "when": ("service_active=false", "service_result!=success"),
        "diagnostic": "inspect_recent_journal",
        "verification": "service_status_after_remediation",
    },
    "running_without_listener": {
        "when": ("service_active=true", "port_listening=false"),
        "diagnostic": "inspect_socket_or_service_config",
        "verification": "listener_and_service_status_after_remediation",
    },
    "dns_upstream_failure": {
        "when": ("resolver_configured=true", "default_route_present=true", "dns_upstream_reachable=false"),
        "diagnostic": "inspect_resolver_and_upstream",
        "verification": "repeat_dns_resolution_and_route_observation",
    },
    "nix_activation_failure": {
        "when": ("nix_operation=switch", "generation_advanced=false"),
        "diagnostic": "inspect_build_activation_evidence",
        "verification": "generation_and_activation_state_after_remediation",
    },
}


class SysadminExpert:
    def __init__(self, backend, *, max_log_lines: int = 200, max_processes: int = 100) -> None:
        if not 1 <= int(max_log_lines) <= 2000:
            raise SysadminError("max_log_lines is out of range")
        if not 1 <= int(max_processes) <= 1000:
            raise SysadminError("max_processes is out of range")
        self.backend = backend
        self.max_log_lines = int(max_log_lines)
        self.max_processes = int(max_processes)

    @staticmethod
    def _bounded(value: str, *, name: str, limit: int = 256) -> str:
        if not isinstance(value, str) or not value.strip():
            raise SysadminError(f"{name} must be a non-empty string")
        if len(value.encode("utf-8")) > limit:
            raise SysadminError(f"{name} exceeds byte limit")
        if any(ord(character) < 0x20 for character in value):
            raise SysadminError(f"{name} contains control characters")
        return value

    def rule_inventory(self) -> dict[str, dict[str, object]]:
        return {name: dict(rule) for name, rule in _RULES.items()}

    def journal(self, unit: str, limit: int = 50) -> dict[str, object]:
        unit = self._bounded(unit, name="unit")
        limit = int(limit)
        if not 1 <= limit <= self.max_log_lines:
            raise SysadminError("journal line limit is out of range")
        lines = self.backend.journal(unit, limit)
        if not isinstance(lines, list):
            raise SysadminError("journal backend returned invalid evidence")
        bounded = [str(line)[:4096] for line in lines[:limit]]
        return {"unit": unit, "lines": bounded, "count": len(bounded)}

    def service_status(self, unit: str) -> dict[str, object]:
        unit = self._bounded(unit, name="unit")
        status = self.backend.service_status(unit)
        if not isinstance(status, dict):
            raise SysadminError("service backend returned invalid status")
        return {"unit": unit, **status}

    def diagnose_service(self, unit: str) -> dict[str, object]:
        status = self.service_status(unit)
        facts = {
            "service_active": bool(status.get("active")),
            "service_result": str(status.get("result", "unknown")),
            "service_substate": str(status.get("substate", "unknown")),
        }
        hypotheses: list[str] = []
        next_diagnostics: list[str] = []
        evidence: dict[str, object] = {"service": status}
        if not facts["service_active"] and facts["service_result"] != "success":
            hypotheses.append("service_failed")
            next_diagnostics.append("inspect_recent_journal")
            evidence["journal"] = self.journal(unit, min(50, self.max_log_lines))["lines"]
        return {
            "status": "diagnosed",
            "facts": facts,
            "hypotheses": hypotheses,
            "next_diagnostics": next_diagnostics,
            "evidence": evidence,
        }

    def diagnose_service_port(self, unit: str, port: int) -> dict[str, object]:
        if not 1 <= int(port) <= 65535:
            raise SysadminError("port is out of range")
        status = self.service_status(unit)
        listener = self.backend.listener(int(port))
        if not isinstance(listener, dict):
            raise SysadminError("listener backend returned invalid evidence")
        active = bool(status.get("active"))
        listening = bool(listener.get("listening"))
        hypotheses: list[str] = []
        next_diagnostics: list[str] = []
        if active and not listening:
            hypotheses.append("running_without_listener")
            next_diagnostics.append("inspect_socket_or_service_config")
        return {
            "status": "diagnosed",
            "facts": {"service_active": active, "port_listening": listening},
            "hypotheses": hypotheses,
            "next_diagnostics": next_diagnostics,
            "evidence": {"service": status, "listener": listener},
        }

    def diagnose_dns(self) -> dict[str, object]:
        network = self.network()
        dns = network.get("dns", {})
        routes = network.get("routes", [])
        facts = {
            "resolver_configured": bool(dns.get("resolver_configured")) if isinstance(dns, dict) else False,
            "default_route_present": any(
                isinstance(route, dict) and route.get("destination") == "default" for route in routes
            ),
            "dns_upstream_reachable": bool(dns.get("upstream_reachable")) if isinstance(dns, dict) else False,
        }
        hypotheses: list[str] = []
        if facts["resolver_configured"] and facts["default_route_present"] and not facts["dns_upstream_reachable"]:
            hypotheses.append("dns_upstream_failure")
        elif not facts["resolver_configured"]:
            hypotheses.append("resolver_not_configured")
        elif not facts["default_route_present"]:
            hypotheses.append("default_route_missing")
        return {
            "status": "diagnosed",
            "facts": facts,
            "hypotheses": hypotheses,
            "evidence": network,
        }

    def processes(self, limit: int = 25) -> dict[str, object]:
        limit = int(limit)
        if not 1 <= limit <= self.max_processes:
            raise SysadminError("process limit is out of range")
        processes = self.backend.process_summary(limit)
        if not isinstance(processes, list):
            raise SysadminError("process backend returned invalid evidence")
        return {"processes": processes[:limit], "count": min(len(processes), limit)}

    def resources(self) -> dict[str, object]:
        result = self.backend.resource_summary()
        if not isinstance(result, dict):
            raise SysadminError("resource backend returned invalid evidence")
        return result

    def network(self) -> dict[str, object]:
        result = self.backend.network_summary()
        if not isinstance(result, dict):
            raise SysadminError("network backend returned invalid evidence")
        return result

    def nix_generations(self, limit: int = 20) -> dict[str, object]:
        limit = int(limit)
        if not 1 <= limit <= 100:
            raise SysadminError("generation limit is out of range")
        generations = self.backend.nix_generations(limit)
        if not isinstance(generations, list):
            raise SysadminError("Nix backend returned invalid generation evidence")
        return {"generations": generations[:limit]}

    def service_action(self, unit: str, action: str) -> dict[str, object]:
        unit = self._bounded(unit, name="unit")
        if action not in {"start", "stop", "restart"}:
            raise SysadminError("service action is not allowlisted")
        before = self.service_status(unit)
        result = self.backend.service_action(unit, action)
        if not isinstance(result, dict):
            raise SysadminError("service backend returned invalid action evidence")
        after = self.service_status(unit)
        accepted = bool(result.get("accepted"))
        expected_active = action in {"start", "restart"}
        verified = accepted and (bool(after.get("active")) is expected_active)
        return {
            "status": "verified" if verified else "verification_failed",
            "accepted": accepted,
            "verified": verified,
            "action": action,
            "unit": unit,
            "before": before,
            "action_evidence": result,
            "after": after,
        }

    def nix_operation(self, operation: str, target: str) -> dict[str, object]:
        if operation not in {"check", "build", "switch"}:
            raise SysadminError("Nix operation is not allowlisted")
        target = self._bounded(target, name="Nix target", limit=1024)
        before = self.backend.nix_generations(1)
        before_generation = before[0].get("generation") if before else None
        evidence = self.backend.nix_operation(operation, target)
        if not isinstance(evidence, dict):
            raise SysadminError("Nix backend returned invalid operation evidence")
        after = self.backend.nix_generations(1)
        after_generation = after[0].get("generation") if after else None
        if operation == "switch":
            verified = bool(evidence.get("accepted")) and after_generation != before_generation
        else:
            verified = bool(evidence.get("accepted"))
        return {
            "status": "verified" if verified else "verification_failed",
            "operation": operation,
            "target": target,
            "accepted": bool(evidence.get("accepted")),
            "verified": verified,
            "before_generation": before_generation,
            "after_generation": after_generation,
            "evidence": evidence,
        }
