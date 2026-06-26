"""Shared utilities for Open Banking MCP."""

import importlib.metadata

from common.audit import AuditEvent, AuditTrail, ListSink, StdoutJSONSink, audited
from common.errors import OpenBankingError

try:
    __version__: str = importlib.metadata.version("open-banking-mcp")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__all__: list[str] = [
    "AuditEvent",
    "AuditTrail",
    "ListSink",
    "OpenBankingError",
    "StdoutJSONSink",
    "__version__",
    "audited",
]
