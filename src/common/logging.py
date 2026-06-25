"""Logging utilities for Open Banking MCP."""

from __future__ import annotations

import logging as _stdlib_logging


def get_logger(name: str) -> _stdlib_logging.Logger:
    """Create a configured logger instance.

    Args:
        name: The name for the logger, typically ``__name__``.

    Returns:
        A configured logger instance.
    """
    return _stdlib_logging.getLogger(name)
