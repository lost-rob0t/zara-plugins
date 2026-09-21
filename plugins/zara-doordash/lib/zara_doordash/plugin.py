from __future__ import annotations

import json
from collections.abc import Mapping

from langchain_core.tools import StructuredTool
from zara.plugins import PluginMetadata, ServicePlugin

from .domain import DoorDashDomain, DoorDashError


PLUGIN_VERSION = "0.1.0"
APPROVAL_METADATA = {"zara_requires_approval": True}


class ZaraDoorDashPlugin(ServicePlugin):
    metadata = PluginMetadata(
        name="zara-doordash",
        version=PLUGIN_VERSION,
        api_version="1",
        description=(
            "Approval-gated DoorDash consumer handoff with generic symbolic "
            "preference learning"
        ),
    )

    def __init__(self) -> None:
        self.domain = DoorDashDomain()
        self.runtime = None
        self.learning_enabled = True
        self.preference_min_observations = 2
        self.preference_limit = 10
        self.preference_min_confidence = 0.5
        self.policy_source = "default"

    def start(self, runtime) -> None:
        self.runtime = runtime
        section = self._section(runtime.configuration)
        self.domain = DoorDashDomain(
            max_url_chars=self._integer(
                section.get("max_url_chars", 2048),
                "max_url_chars",
                256,
                8192,
            )
        )
        self.learning_enabled = self._boolean(
            section.get("learning_enabled", True),
            "learning_enabled",
        )
        self.preference_min_observations = self._integer(
            section.get("preference_min_observations", 2),
            "preference_min_observations",
            1,
            1000,
        )
        self.preference_limit = self._integer(
            section.get("preference_limit", 10),
            "preference_limit",
            1,
            100,
        )
        self.preference_min_confidence = self._number(
            section.get("preference_min_confidence", 0.5),
            "preference_min_confidence",
            0.0,
            1.0,
        )
        provider = section.get("commerce_provider", "doordash")
        confirmation = section.get("commerce_confirmation", "always")
        if provider != "doordash":
            raise DoorDashError("commerce_provider must be doordash")
        if confirmation != "always":
            raise DoorDashError("commerce_confirmation must remain always")
        source = section.get("policy_source", "default")
        if not isinstance(source, str) or not source:
            raise DoorDashError("policy_source must be a non-empty string")
        self.policy_source = source

    def stop(self) -> None:
        self.runtime = None

    def status(self) -> str:
        return self._json(
            {
                "status": "ready",
                "provider": "doordash",
                "checkout_mode": "consumer_handoff",
                "consumer_checkout_api": "not_publicly_available",
                "browser_handoff": self._resolve("browser.tab.open") is not None,
                "policy_source": self.policy_source,
                "preference_learning": {
                    "enabled": self.learning_enabled,
                    "observe_available": self._resolve("memory.preference.observe") is not None,
                    "patterns_available": self._resolve("memory.preference.patterns") is not None,
                    "min_observations": self.preference_min_observations,
                    "max_patterns": self.preference_limit,
                    "min_confidence": self.preference_min_confidence,
                },
                "purchase_completed": False,
            }
        )

    def prepare(
        self,
        item: str,
        merchant: str = "",
        modifiers: list[str] | None = None,
        context: dict[str, str] | None = None,
    ) -> str:
        return self._json(
            self.domain.prepare(
                item=item,
                merchant=merchant,
                modifiers=modifiers,
                context=context,
            )
        )

    def checkout(
        self,
        item: str,
        merchant: str = "",
        modifiers: list[str] | None = None,
        context: dict[str, str] | None = None,
    ) -> str:
        plan = self.domain.prepare(
            item=item,
            merchant=merchant,
            modifiers=modifiers,
            context=context,
        )
        browser = {"status": "unavailable", "reason": "browser-capability-unavailable"}
        browser_handle = self._resolve("browser.tab.open")
        if browser_handle is not None and self.runtime is not None:
            try:
                browser = self._result_mapping(
                    self.runtime.invoke_capability(
                        browser_handle,
                        {"url": plan["url"]},
                    )
                )
                plan["status"] = "handoff_opened"
            except Exception as error:
                browser = {
                    "status": "unavailable",
                    "reason": type(error).__name__,
                }

        learning: dict[str, object] = {
            "status": "disabled" if not self.learning_enabled else "not_observed"
        }
        preference_observe_handle = self._resolve("memory.preference.observe")
        if (
            self.learning_enabled
            and plan["status"] == "handoff_opened"
            and preference_observe_handle is not None
            and self.runtime is not None
        ):
            observation = self.domain.preference_observation(
                item=item,
                merchant=merchant,
                context=context,
            )
            try:
                learning = self._result_mapping(
                    self.runtime.invoke_capability(
                        preference_observe_handle,
                        observation,
                    )
                )
            except Exception as error:
                learning = {
                    "status": "unavailable",
                    "reason": type(error).__name__,
                }

        plan["browser"] = browser
        plan["learning"] = learning
        plan["purchase_completed"] = False
        plan["user_confirmation_required"] = True
        return self._json(plan)

    def preferences(
        self,
        context: dict[str, str] | None = None,
        min_observations: int | None = None,
        limit: int | None = None,
    ) -> str:
        preference_patterns_handle = self._resolve("memory.preference.patterns")
        if preference_patterns_handle is None or self.runtime is None:
            return self._json(
                {
                    "status": "unavailable",
                    "reason": "preference-pattern-capability-unavailable",
                    "patterns": [],
                }
            )
        minimum = (
            self.preference_min_observations
            if min_observations is None
            else max(
                self.preference_min_observations,
                self._integer(min_observations, "min_observations", 1, 1000),
            )
        )
        maximum = (
            self.preference_limit
            if limit is None
            else min(
                self.preference_limit,
                self._integer(limit, "limit", 1, 100),
            )
        )
        request = {
            "domain": "food",
            "provider": "doordash",
            "context": dict(context or {}),
            "min_observations": minimum,
            "limit": maximum,
        }
        try:
            result = self._result_mapping(
                self.runtime.invoke_capability(
                    preference_patterns_handle,
                    request,
                )
            )
            patterns = result.get("patterns", [])
            if not isinstance(patterns, list):
                raise DoorDashError("preference patterns must be a list")
            result["patterns"] = [
                pattern
                for pattern in patterns
                if isinstance(pattern, Mapping)
                and self._pattern_confidence(pattern) >= self.preference_min_confidence
            ]
            return self._json(result)
        except Exception as error:
            return self._json(
                {
                    "status": "unavailable",
                    "reason": type(error).__name__,
                    "patterns": [],
                }
            )

    def tools(self):
        return (
            StructuredTool.from_function(
                func=self.status,
                name="doordash.status",
                description=(
                    "Report DoorDash handoff and preference-learning capability "
                    "without claiming a public consumer checkout API."
                ),
            ),
            StructuredTool.from_function(
                func=self.prepare,
                name="doordash.prepare",
                description=(
                    "Prepare a bounded DoorDash consumer search handoff for a meal "
                    "or item. This performs no purchase side effect."
                ),
            ),
            StructuredTool.from_function(
                func=self.checkout,
                name="doordash.checkout",
                description=(
                    "After explicit user approval, open the prepared DoorDash "
                    "consumer handoff and record the confirmed selection as a "
                    "low-authority preference observation. Provider UI still owns "
                    "final payment and order submission."
                ),
                metadata=APPROVAL_METADATA,
            ),
            StructuredTool.from_function(
                func=self.preferences,
                name="doordash.preferences",
                description=(
                    "Read learned DoorDash meal/item patterns for the supplied "
                    "context through symbolic memory."
                ),
            ),
        )

    def _resolve(self, capability: str):
        if self.runtime is None:
            return None
        try:
            return self.runtime.resolve_capability(capability)
        except (LookupError, RuntimeError):
            return None

    @staticmethod
    def _result_mapping(value: object) -> dict[str, object]:
        if isinstance(value, Mapping):
            return dict(value)
        if isinstance(value, str):
            decoded = json.loads(value)
            if isinstance(decoded, Mapping):
                return dict(decoded)
        raise DoorDashError("composed capability returned invalid structured evidence")

    @staticmethod
    def _json(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _section(configuration: object) -> Mapping[str, object]:
        if configuration is None:
            return {}
        if not isinstance(configuration, Mapping):
            raise DoorDashError("zara-doordash configuration must be a table")
        return configuration

    @staticmethod
    def _pattern_confidence(pattern: Mapping[str, object]) -> float:
        value = pattern.get("confidence", pattern.get("preference_ratio", 0.0))
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return 0.0
        return float(value)

    @staticmethod
    def _boolean(value: object, name: str) -> bool:
        if not isinstance(value, bool):
            raise DoorDashError(f"{name} must be true or false")
        return value

    @staticmethod
    def _integer(
        value: object,
        name: str,
        minimum: int,
        maximum: int,
    ) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise DoorDashError(f"{name} must be an integer")
        if not minimum <= value <= maximum:
            raise DoorDashError(f"{name} is out of range")
        return value

    @staticmethod
    def _number(
        value: object,
        name: str,
        minimum: float,
        maximum: float,
    ) -> float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise DoorDashError(f"{name} must be a number")
        value = float(value)
        if not minimum <= value <= maximum:
            raise DoorDashError(f"{name} is out of range")
        return value


def create_plugin():
    return ZaraDoorDashPlugin()
