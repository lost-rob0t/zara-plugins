"""Sourced web and wiki knowledge providers for Zara."""

from .brave import BraveProvider, BraveProviderError
from .core import KnowledgeEngine, SourcedResult
from .store import LocalWikiProvider, WikiStore
from .wiki import GateCatalog, GateSpec, MediaWikiGate, WikiGateError, WikiManager

__all__ = [
    "BraveProvider",
    "BraveProviderError",
    "GateCatalog",
    "GateSpec",
    "KnowledgeEngine",
    "LocalWikiProvider",
    "MediaWikiGate",
    "SourcedResult",
    "WikiGateError",
    "WikiManager",
    "WikiStore",
]
