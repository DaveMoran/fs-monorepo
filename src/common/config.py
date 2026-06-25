"""Configuration management for Open Banking MCP."""

from __future__ import annotations


def get_config(key: str, default: str | None = None) -> str | None:
    """Retrieve a configuration value by key.

    Args:
        key: The configuration key to look up.
        default: Fallback value if key is not found.

    Returns:
        The configuration value, or the default if not found.
    """
    return default
