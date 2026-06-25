"""Tests for the common and banking_client package stubs."""

from __future__ import annotations

import banking_client
from common import OpenBankingError, __version__
from common.config import get_config
from common.errors import AuthenticationError, ConfigurationError
from common.logging import get_logger


def test_version_is_string() -> None:
    """Verify __version__ is a string."""
    assert isinstance(__version__, str)


def test_get_config_returns_default() -> None:
    """Verify get_config returns the default for a missing key."""
    assert get_config("missing_key", "fallback") == "fallback"


def test_get_logger_returns_logger() -> None:
    """Verify get_logger returns a logger with the given name."""
    assert get_logger("test").name == "test"


def test_error_hierarchy() -> None:
    """Verify error classes are subclasses of OpenBankingError."""
    assert issubclass(ConfigurationError, OpenBankingError)
    assert issubclass(AuthenticationError, OpenBankingError)


def test_banking_client_version_is_string() -> None:
    """Verify banking_client.__version__ is a string."""
    assert isinstance(banking_client.__version__, str)
