"""Structured Emacs integration for Zara."""

from .client import EmacsClient, EmacsError
from .config import EmacsConfig, EmacsConfigError
from .expert import (
    EMACS_EXPERT_ID,
    EMACS_EXPERT_OPERATIONS,
    EMACS_EXPERT_SOURCE,
    EmacsExpertAdapter,
    EmacsExpertAdapterError,
    validate_emacs_descriptor,
)

__all__ = [
    "EMACS_EXPERT_ID",
    "EMACS_EXPERT_OPERATIONS",
    "EMACS_EXPERT_SOURCE",
    "EmacsClient",
    "EmacsError",
    "EmacsConfig",
    "EmacsConfigError",
    "EmacsExpertAdapter",
    "EmacsExpertAdapterError",
    "validate_emacs_descriptor",
]
