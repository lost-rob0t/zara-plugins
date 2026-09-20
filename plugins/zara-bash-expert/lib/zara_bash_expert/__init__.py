"""Zara BashExpert adapter package.

Only the typed boundary and its fail-closed error are public.  The lower-level
adapter implementation stays internal so callers cannot opt around the
ZARA-EXPERT/1 admission boundary by importing the package root.
"""

from .boundary import ZaraBashExpertBoundaryPlugin, create_plugin
from .plugin import BashExpertAdapterError

__all__ = [
    "BashExpertAdapterError",
    "ZaraBashExpertBoundaryPlugin",
    "create_plugin",
]
