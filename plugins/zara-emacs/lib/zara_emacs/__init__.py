"""Structured Emacs integration for Zara."""

from .client import EmacsClient, EmacsError
from .config import EmacsConfig, EmacsConfigError

__all__ = ["EmacsClient", "EmacsError", "EmacsConfig", "EmacsConfigError"]
