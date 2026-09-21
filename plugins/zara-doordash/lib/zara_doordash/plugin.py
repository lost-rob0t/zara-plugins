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
        self.browser_handle = None
        self.preference_observe_handle = None
        self.preference_patterns_handle = None
        self.learning_enabled = True
        self.preference_min_observations = 2
        self.preference_limit = 10

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
        self.browser_handle = self._resolve("browser.tab.open")
        self.preference_observe_handle = self._resolve("memory.preference.observe")
        self.preference_patterns_handle = self._resolve("memory.preference.patterns")

    def stop(self) -> None:
        self.runtime = None
        self.browser_handle = None
        self.preference_observe_handle = None
        self.preference_patterns_handle = None

    def status(self) -> str:
        return self._json(
            {
                "status": "ready",
                "provider": "doordash",
                "checkout_mode": "consumer_handoff",
                "consumer_checkout_api": "not_publicly_available",
                "browser_handoff": self.browser_handle is not None,
                "preference_learning": {
                    "enabled": self.learning_enabled,
                    "observe_available": self.preference_observe_handle is not None,
                    "patterns_available": self.preference_patterns_handle is not None,
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
        if self.browser_handle is not None and self.runtime is not None:
            try:
                browser = self._result_mapping(
                    self.runtime.invoke_capability(
                        self.browser_handle,
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
            "status": "disabled" if not self.learning_enabled else "unavailable"
        }
        if (
            self.learning_enabled
            and self.preference_observe_handle is not None
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
                        self.preference_observe_handle,
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
        if self.preference_patterns_handle is None or self.runtime is None:
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
            else self._integer(min_observations, "min_observations", 1, 1000)
        )
        maximum = (
            self.preference_limit
            if limit is None
            else self._integer(limit, "limit", 1, 100)
        )
        request = {
            "domain": "food",
            "provider": "doordash",
            "context": dict(context or {}),
            "min_observations": minimum,
            "limit": maximum,
        }
        try:
            return self._json(
                self._result_mapping(
                    self.runtime.invoke_capability(
                        self.preference_patterns_handle,
                        request,
                    )
                )
            )
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
        if not isinstance(configuration, Mapping):
            return {}
        plugins = configuration.get("plugins", {})
        if not isinstance(plugins, Mapping):
            return {}
        section = plugins.get("zara-doordash", {})
        if not isinstance(section, Mapping):
            raise DoorDashError("plugins.zara-doordash must be a table")
        return section

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


def create_plugin():
    return ZaraDoorDashPlugin()
