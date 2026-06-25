"""Agent package for Open Banking MCP."""

import importlib.metadata

try:
    __version__: str = importlib.metadata.version("open-banking-mcp")
except importlib.metadata.PackageNotFoundError:
    __version__: str = "0.0.0"
