"""Custom error types for Open Banking MCP."""

from __future__ import annotations


class OpenBankingError(Exception):
    """Base exception for all Open Banking MCP errors."""


class ConfigurationError(OpenBankingError):
    """Raised when a required configuration value is missing or invalid."""


class AuthenticationError(OpenBankingError):
    """Raised when authentication with the FDX API fails."""
