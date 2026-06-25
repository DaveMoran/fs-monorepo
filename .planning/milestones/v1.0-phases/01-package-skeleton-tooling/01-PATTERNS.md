# Phase 1: Package Skeleton & Tooling - Pattern Map

**Mapped:** 2026-06-24
**Files analyzed:** 16
**Analogs found:** 0 / 16

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `pyproject.toml` | config | N/A | none | N/A |
| `src/banking_client/__init__.py` | config | N/A | none | N/A |
| `src/banking_client/py.typed` | config | N/A | none | N/A |
| `src/mcp_server/__init__.py` | config | N/A | none | N/A |
| `src/mcp_server/py.typed` | config | N/A | none | N/A |
| `src/agent/__init__.py` | config | N/A | none | N/A |
| `src/agent/py.typed` | config | N/A | none | N/A |
| `src/common/__init__.py` | config | N/A | none | N/A |
| `src/common/py.typed` | config | N/A | none | N/A |
| `src/common/config.py` | utility | request-response | none | N/A |
| `src/common/logging.py` | utility | N/A | none | N/A |
| `src/common/errors.py` | model | N/A | none | N/A |

## Pattern Assignments

No existing codebase analogs -- this is a greenfield project. All patterns come from RESEARCH.md.

### `pyproject.toml` (config)

**Pattern source:** RESEARCH.md "Complete pyproject.toml Structure"

Key sections:
- `[build-system]` with hatchling
- `[tool.hatch.build.targets.wheel]` explicitly listing all 4 packages under `src/`
- `[tool.mypy]` with `strict = true`, `mypy_path = "$MYPY_CONFIG_FILE_DIR/src"`, explicit packages list
- `[tool.ruff]` with `target-version = "py312"`, `line-length = 120`, `src = ["src"]`
- `[tool.ruff.lint]` selecting `["E", "F", "I", "B", "UP", "SIM", "D"]`
- `[tool.ruff.lint.pydocstyle]` with `convention = "google"`
- `[tool.pytest.ini_options]` with `asyncio_mode = "auto"`
- `mcp>=1.27,<2` in dependencies

### `src/{banking_client,mcp_server,agent}/__init__.py` (config)

**Pattern source:** RESEARCH.md "Pattern 1: Skeleton __init__.py with Dynamic Version"

```python
"""<Package description> for Open Banking MCP."""

import importlib.metadata

try:
    __version__: str = importlib.metadata.version("open-banking-mcp")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"
```

### `src/common/__init__.py` (config, re-exports)

**Pattern source:** RESEARCH.md "Pattern 3: Convenience Re-exports"

```python
"""Shared utilities for Open Banking MCP."""

import importlib.metadata

from common.errors import OpenBankingError

try:
    __version__: str = importlib.metadata.version("open-banking-mcp")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"

__all__: list[str] = [
    "OpenBankingError",
    "__version__",
]
```

### `src/common/config.py` (utility stub)

**Pattern source:** RESEARCH.md "Pattern 2: Stub Module with Type Annotations"

```python
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
```

### `src/common/errors.py` (model stub)

**Pattern source:** RESEARCH.md "common/errors.py Stub"

```python
"""Custom error types for Open Banking MCP."""

from __future__ import annotations


class OpenBankingError(Exception):
    """Base exception for all Open Banking MCP errors."""


class ConfigurationError(OpenBankingError):
    """Raised when a required configuration value is missing or invalid."""


class AuthenticationError(OpenBankingError):
    """Raised when authentication with the FDX API fails."""
```

### `src/common/logging.py` (utility stub)

**Pattern source:** RESEARCH.md anti-pattern warning on stdlib shadowing

Critical: Must not do bare `import logging` inside this file. Use `import logging as _stdlib_logging` to avoid circular import with stdlib.

### `src/*/py.typed` (PEP 561 markers)

Empty files. No content needed.

## Shared Patterns

### Dynamic Version (all `__init__.py` files)
**Apply to:** `src/banking_client/__init__.py`, `src/mcp_server/__init__.py`, `src/agent/__init__.py`, `src/common/__init__.py`

Use `importlib.metadata.version("open-banking-mcp")` with `PackageNotFoundError` fallback to `"0.0.0"`.

### Google-Style Docstrings (all `.py` files)
**Apply to:** Every Python file

All modules need a module-level docstring. All public functions/classes need Google-style docstrings with Args/Returns sections.

### Type Annotations (all stub files)
**Apply to:** `src/common/config.py`, `src/common/logging.py`, `src/common/errors.py`

Full type annotations on all function signatures. Include `from __future__ import annotations`.

### Stdlib Logging Shadow Avoidance
**Apply to:** `src/common/logging.py` only

Inside `common/logging.py`, alias stdlib logging: `import logging as _stdlib_logging`.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| All 16 files | various | various | Greenfield project -- no existing source code. Use RESEARCH.md patterns. |

## Metadata

**Analog search scope:** entire repository
**Files scanned:** 0 source files (greenfield -- only README.md and planning artifacts exist)
**Pattern extraction date:** 2026-06-24
