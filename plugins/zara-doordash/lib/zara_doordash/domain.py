from __future__ import annotations

from urllib.parse import quote


class DoorDashError(ValueError):
    pass


class DoorDashDomain:
    SEARCH_BASE = "https://www.doordash.com/en/search/store/"

    def __init__(self, *, max_url_chars: int = 2048) -> None:
        if isinstance(max_url_chars, bool) or not isinstance(max_url_chars, int):
            raise DoorDashError("max_url_chars must be an integer")
        if not 256 <= max_url_chars <= 8192:
            raise DoorDashError("max_url_chars is out of range")
        self.max_url_chars = max_url_chars

    def prepare(
        self,
        *,
        item: str,
        merchant: str = "",
        modifiers: list[str] | None = None,
        context: dict[str, str] | None = None,
    ) -> dict[str, object]:
        item = self._text(item, "item", 256)
        merchant = self._optional_text(merchant, "merchant", 256)
        modifier_list = self._modifiers(modifiers)
        normalized_context = self._context(context)

        query_parts = [part for part in (merchant, item, *modifier_list) if part]
        query = " ".join(query_parts)
        url = self.SEARCH_BASE + quote(query, safe="")
        if len(url) > self.max_url_chars:
            raise DoorDashError("DoorDash handoff URL is too long")

        return {
            "provider": "doordash",
            "status": "handoff_ready",
            "checkout_mode": "consumer_handoff",
            "url": url,
            "item": item,
            "merchant": merchant,
            "modifiers": modifier_list,
            "context": normalized_context,
            "purchase_completed": False,
            "user_confirmation_required": True,
        }

    def preference_observation(
        self,
        *,
        item: str,
        merchant: str = "",
        context: dict[str, str] | None = None,
    ) -> dict[str, object]:
        return {
            "domain": "food",
            "item": self._text(item, "item", 256),
            "signal": "selected",
            "provider": "doordash",
            "merchant": self._optional_text(merchant, "merchant", 256),
            "context": self._context(context),
        }

    @staticmethod
    def _text(value: object, name: str, limit: int) -> str:
        if not isinstance(value, str):
            raise DoorDashError(f"{name} must be a string")
        value = value.strip()
        if not value:
            raise DoorDashError(f"{name} must not be empty")
        if len(value) > limit:
            raise DoorDashError(f"{name} exceeds length limit")
        if any(ord(character) < 0x20 for character in value):
            raise DoorDashError(f"{name} contains control characters")
        return value

    @classmethod
    def _optional_text(cls, value: object, name: str, limit: int) -> str:
        if value in (None, ""):
            return ""
        return cls._text(value, name, limit)

    @classmethod
    def _modifiers(cls, modifiers: list[str] | None) -> list[str]:
        if modifiers is None:
            return []
        if not isinstance(modifiers, list):
            raise DoorDashError("modifiers must be a list")
        if len(modifiers) > 16:
            raise DoorDashError("too many modifiers")
        return [cls._text(value, "modifier", 256) for value in modifiers]

    @classmethod
    def _context(cls, context: dict[str, str] | None) -> dict[str, str]:
        if context is None:
            return {}
        if not isinstance(context, dict):
            raise DoorDashError("context must be an object")
        if len(context) > 16:
            raise DoorDashError("context has too many fields")
        normalized: dict[str, str] = {}
        for key, value in context.items():
            normalized[cls._text(key, "context key", 64)] = cls._text(
                value,
                f"context value {key}",
                256,
            )
        return normalized
