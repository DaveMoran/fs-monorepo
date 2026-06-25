"""Shared utilities for Open Banking MCP."""

import importlib.metadata

from common.errors import OpenBankingError

try:
    __version__: str = importlib.metadata.version("open-banking-mcp")
except importlib.metadata.PackageNotFoundError:
    __version__: str = "0.0.0"

__all__: list[str] = [
    "OpenBankingError",
    "__version__",
]
