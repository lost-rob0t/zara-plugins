from __future__ import annotations

import json
import time
from collections import deque


class HealthError(RuntimeError):
    pass


class SystemClock:
    @staticmethod
    def now():
        return time.time()


class HealthDomain:
    VALID = {"healthy", "degraded", "unhealthy", "unknown"}

    def __init__(self, probes, *, clock=None, history_limit=32, hysteresis_count=2, max_evidence_bytes=16384):
        if not isinstance(probes, dict) or not probes or len(probes) > 128:
            raise HealthError("probes must contain between 1 and 128 configured probes")
        if not 1 <= int(history_limit) <= 1000:
            raise HealthError("history_limit is out of range")
        if not 1 <= int(hysteresis_count) <= 20:
            raise HealthError("hysteresis_count is out of range")
        if not 256 <= int(max_evidence_bytes) <= 1_048_576:
            raise HealthError("max_evidence_bytes is out of range")
        self.probes = dict(probes)
        self.clock = clock or SystemClock()
        self.history_limit = int(history_limit)
        self.hysteresis_count = int(hysteresis_count)
        self.max_evidence_bytes = int(max_evidence_bytes)
        self._history = {name: deque(maxlen=self.history_limit) for name in probes}
        self._state = {}
        self._pending = {}
        self._events = []

    def _normalize(self, name, raw):
        if not isinstance(raw, dict):
            raise HealthError("probe result must be an object")
        status = raw.get("status")
        if status not in self.VALID:
            raise HealthError("probe status is invalid")
        unit = raw.get("unit")
        if not isinstance(unit, str) or len(unit) > 64:
            raise HealthError("probe unit is invalid")
        evidence = raw.get("evidence", {})
        if not isinstance(evidence, dict):
            raise HealthError("probe evidence must be an object")
        encoded = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
        if len(encoded) > self.max_evidence_bytes:
            raise HealthError("probe evidence exceeds byte limit")
        return {
            "probe": name,
            "status": status,
            "value": raw.get("value"),
            "unit": unit,
            "evidence": evidence,
            "observed_at": float(self.clock.now()),
        }

    def _unknown(self, name, error):
        return {
            "probe": name,
            "status": "unknown",
            "value": None,
            "unit": "",
            "evidence": {"error_type": type(error).__name__},
            "observed_at": float(self.clock.now()),
        }

    def _accept_state(self, name, result):
        current = self._state.get(name)
        if current is None:
            self._state[name] = result
            self._pending.pop(name, None)
            return
        if result["status"] == current["status"]:
            self._state[name] = result
            self._pending.pop(name, None)
            return
        pending = self._pending.get(name)
        if pending is None or pending["status"] != result["status"]:
            pending = {"status": result["status"], "count": 1, "latest": result}
            self._pending[name] = pending
        else:
            pending["count"] += 1
            pending["latest"] = result
        if pending["count"] >= self.hysteresis_count:
            previous = current["status"]
            accepted = pending["latest"]
            self._state[name] = accepted
            self._pending.pop(name, None)
            self._events.append({
                "type": "health.state_changed",
                "probe": name,
                "from": previous,
                "to": accepted["status"],
                "observed_at": accepted["observed_at"],
                "evidence": accepted["evidence"],
            })

    def poll(self):
        snapshot = {}
        for name in sorted(self.probes):
            if not isinstance(name, str) or not name or len(name) > 128:
                raise HealthError("probe name is invalid")
            try:
                result = self._normalize(name, self.probes[name].run())
            except Exception as error:
                result = self._unknown(name, error)
            self._history[name].append(result)
            self._accept_state(name, result)
            snapshot[name] = result
        return snapshot

    def state(self):
        return {name: dict(value) for name, value in self._state.items()}

    def history(self, name):
        if name not in self._history:
            raise HealthError("probe does not exist")
        return list(self._history[name])

    def drain_events(self):
        events = list(self._events)
        self._events.clear()
        return events

    def export_facts(self):
        facts = []
        for name in sorted(self._state):
            result = self._state[name]
            facts.append({
                "predicate": "health_status",
                "args": [name, result["status"]],
                "observed_at": result["observed_at"],
                "evidence": result["evidence"],
            })
        return facts
