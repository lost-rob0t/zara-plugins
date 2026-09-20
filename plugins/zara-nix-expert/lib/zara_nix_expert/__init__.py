"""Zara NixExpert adapter package.

Only the typed boundary and its fail-closed error are public.  The lower-level
adapter implementation stays internal so callers cannot opt around the
ZARA-EXPERT/1 admission boundary by importing the package root.
"""

from .boundary import ZaraNixExpertBoundaryPlugin, create_plugin
from .plugin import NixExpertAdapterError

__all__ = [
    "NixExpertAdapterError",
    "ZaraNixExpertBoundaryPlugin",
    "create_plugin",
]
