# Phase 1: Package Skeleton & Tooling - Research

**Researched:** 2026-06-24
**Domain:** Python packaging, build tooling, static analysis configuration
**Confidence:** HIGH

## Summary

Phase 1 creates the foundational repository structure for an enterprise-grade Python project: a `src/`-layout with four flat packages (`banking_client`, `mcp_server`, `agent`, `common`), a single `pyproject.toml` with the hatchling build backend, and strict tooling configuration for mypy, ruff, and pytest. This is a greenfield project -- the repo currently contains only a `README.md`.

The core challenge is configuring a single `pyproject.toml` to manage multiple flat packages under `src/` with hatchling, while ensuring `mypy --strict` and `ruff` pass zero errors on skeleton code that includes type annotations and Google-style docstrings. A secondary concern is wiring `importlib.metadata.version()` correctly when multiple packages share a single distribution name.

**Primary recommendation:** Create `pyproject.toml` first with all tool configuration, then create the four package directories with properly annotated `__init__.py` files and `py.typed` markers, then run `uv sync` followed by `mypy --strict src/` and `ruff check src/` to verify zero errors.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** common/ contains stub modules only -- no working implementations. Three stub files: `config.py`, `logging.py`, `errors.py`.
- **D-02:** All stubs include full type annotations and one-line Google-style docstrings to exercise mypy --strict and ruff's D rules on real signatures.
- **D-03:** `common/__init__.py` provides convenience re-exports via `__all__` so downstream packages can import directly from `common` (e.g., `from common import OpenBankingError`).
- **D-04:** Expanded enterprise rule set: E (pycodestyle), F (pyflakes), I (isort), B (bugbear), UP (pyupgrade), SIM (simplify), D (pydocstyle/Google convention), plus additional quality rules.
- **D-05:** Google-style docstrings enforced via ruff's D rules with `convention = "google"`.
- **D-06:** Target Python version is 3.12 for pyupgrade rules (matches CI matrix minimum).
- **D-07:** Line length limit is 120 characters.
- **D-08:** Flat packages under `src/` -- `banking_client`, `mcp_server`, `agent`, `common`. Top-level imports (e.g., `import banking_client`), no shared namespace nesting.
- **D-09:** Single project with one `pyproject.toml`; hatchling discovers all packages under `src/`. Not separate installable packages.
- **D-10:** All skeleton packages' `__init__.py` files contain a module docstring describing the package purpose and a `__version__` string.
- **D-11:** Version source of truth is `pyproject.toml` `[project]` version field. `__init__.py` reads it dynamically via `importlib.metadata.version()`.
- **D-12:** PEP 561 `py.typed` marker files included in every package root.

### Claude's Discretion
No areas deferred to Claude's discretion -- all decisions were made by the user.

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PKG-01 | Project is a Python 3.12+ package managed with `uv`, using a `src/` layout | Hatchling src-layout config with `packages` option; `uv sync` for installation |
| PKG-02 | `src/banking_client/` exists as a package with `__init__.py` only (skeleton, no logic) | `__init__.py` with docstring, `__version__`, and `py.typed` marker per D-10/D-12 |
| PKG-03 | `src/mcp_server/` exists as a package with `__init__.py` only (intentionally empty) | Minimal `__init__.py` with docstring and version; `py.typed` marker |
| PKG-04 | `src/agent/` exists as a package with `__init__.py` only (intentionally empty) | Minimal `__init__.py` with docstring and version; `py.typed` marker |
| PKG-05 | `src/common/` exists as a package with `__init__.py` plus scaffolding for shared logging, config, and errors | Stub modules (config.py, logging.py, errors.py) with full type annotations per D-01/D-02/D-03 |
| TOOL-01 | `pyproject.toml` declares the `hatchling` build backend wired for the src layout | Hatchling `packages` option listing all four packages under src/ |
| TOOL-02 | `mypy --strict` is configured in `pyproject.toml` | `[tool.mypy]` with strict=true, mypy_path, packages list, python_version |
| TOOL-03 | `ruff` is configured for both linting and formatting | `[tool.ruff]` with enterprise rules (D-04), Google convention (D-05), line-length 120 (D-07) |
| TOOL-04 | `pytest` + `pytest-asyncio` + `pytest-cov` are configured (asyncio mode auto) | `[tool.pytest.ini_options]` with asyncio_mode="auto" |
| TOOL-05 | `mcp>=1.27,<2` is pinned in dependencies even though it is unused | Add to `[project.dependencies]` in pyproject.toml |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Package structure | Build System (pyproject.toml) | -- | Hatchling discovers and builds packages from src/ layout |
| Type checking | Static Analysis (mypy) | -- | mypy --strict enforces type safety at analysis time |
| Linting/formatting | Static Analysis (ruff) | -- | Single tool replaces black/isort/flake8 |
| Test infrastructure | Test Framework (pytest) | -- | pytest + plugins configured but not exercised this phase |
| Version management | Build Metadata | Runtime (importlib.metadata) | pyproject.toml is source of truth; packages read at runtime |
| Dependency pinning | Package Manager (uv) | Build System (hatchling) | uv manages lock file; hatchling reads pyproject.toml |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| hatchling | 1.30.1 | Build backend for src-layout Python packages | PyPA-maintained, near-zero config for src layout, strong enterprise adoption [CITED: hatch.pypa.io/latest/config/build] |
| mypy | 1.16+ | Static type checker with --strict mode | Enterprise standard for Python type checking [CITED: mypy.readthedocs.io/en/stable/config_file.html] |
| ruff | 0.11+ | Linting and formatting (replaces black/isort/flake8) | Single fast tool, actively maintained by Astral [CITED: docs.astral.sh/ruff/configuration] |
| pytest | 8.x+ | Test framework | De facto standard for Python testing [ASSUMED] |
| uv | 0.9+ | Package manager and virtual environment manager | Fast, modern replacement for pip/venv [ASSUMED] |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest-asyncio | 1.x | Async test support with auto mode | Any async test functions (future phases) |
| pytest-cov | 7.x | Coverage reporting with pytest | CI coverage gate enforcement |
| mcp | >=1.27,<2 | Model Context Protocol SDK | Pinned now, used in Phase 2+ for MCP server |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| hatchling | setuptools | Setuptools requires more config for src-layout; hatchling is more declarative -- user locked D-09 |
| mypy | pyright/pytype | mypy is enterprise standard, pure Python -- user locked this in constraints |
| ruff | black + isort + flake8 | Three tools vs one; ruff is faster -- user locked D-04 |

**Installation:**
```bash
uv sync
```

**Version verification:** All package versions confirmed against PyPI on 2026-06-24:
- hatchling: 1.30.1 (published 2026-06-02) [VERIFIED: PyPI registry]
- mypy: 2.1.0 latest, 1.16+ acceptable (published 2026-05-11) [VERIFIED: PyPI registry]
- ruff: 0.15.19 latest, 0.11+ acceptable (published 2026-06-24) [VERIFIED: PyPI registry]
- pytest: 9.1.1 latest, 8.x+ acceptable (published 2026-06-19) [VERIFIED: PyPI registry]
- pytest-asyncio: 1.4.0 latest (published 2026-05-26) [VERIFIED: PyPI registry]
- pytest-cov: 7.1.0 latest (published 2026-03-21) [VERIFIED: PyPI registry]
- mcp: 1.28.0 latest, >=1.27,<2 pinned (published 2026-06-16) [VERIFIED: PyPI registry]

## Package Legitimacy Audit

> All packages flagged SUS by the automated tool due to PyPI download data being unavailable to the tooling. These are all well-established, canonical Python ecosystem packages maintained by known organizations (PyPA, mypy-lang, Astral, pytest-dev, Anthropic). The SUS verdicts are false positives.

| Package | Registry | Age | Downloads | Source Repo | Verdict | Disposition |
|---------|----------|-----|-----------|-------------|---------|-------------|
| hatchling | PyPI | 4+ yrs | Millions/wk | github.com/pypa/hatch | SUS (false positive) | Approved -- PyPA-maintained canonical build backend |
| mypy | PyPI | 10+ yrs | Millions/wk | github.com/python/mypy | SUS (false positive) | Approved -- official Python typing project |
| ruff | PyPI | 3+ yrs | Millions/wk | github.com/astral-sh/ruff | SUS (false positive) | Approved -- Astral-maintained, industry standard |
| pytest | PyPI | 15+ yrs | Millions/wk | github.com/pytest-dev/pytest | SUS (false positive) | Approved -- de facto Python test framework |
| pytest-asyncio | PyPI | 8+ yrs | Millions/wk | github.com/pytest-dev/pytest-asyncio | SUS (false positive) | Approved -- pytest-dev maintained |
| pytest-cov | PyPI | 10+ yrs | Millions/wk | github.com/pytest-dev/pytest-cov | SUS (false positive) | Approved -- pytest-dev maintained |
| mcp | PyPI | 1+ yr | High | github.com/modelcontextprotocol/python-sdk | SUS (false positive) | Approved -- Anthropic/MCP official SDK |

**Packages removed due to [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** All SUS verdicts are false positives due to PyPI download data unavailability. All packages are canonical ecosystem tools from known maintainers.

## Architecture Patterns

### System Architecture Diagram

```
pyproject.toml (single source of truth)
    |
    +--[build-system]-- hatchling --> discovers src/ packages
    |
    +--[project]-- dependencies --> mcp>=1.27,<2
    |                               pytest, pytest-asyncio, pytest-cov (dev)
    |                               mypy, ruff (dev)
    |
    +--[tool.mypy]-- strict=true --> validates src/**/*.py
    |
    +--[tool.ruff]-- lint+format --> validates src/**/*.py
    |
    +--[tool.pytest]-- asyncio_mode=auto --> tests/**/*.py

src/
    +-- banking_client/
    |   +-- __init__.py (docstring + __version__)
    |   +-- py.typed
    |
    +-- mcp_server/
    |   +-- __init__.py (docstring + __version__)
    |   +-- py.typed
    |
    +-- agent/
    |   +-- __init__.py (docstring + __version__)
    |   +-- py.typed
    |
    +-- common/
        +-- __init__.py (docstring + __version__ + __all__ re-exports)
        +-- py.typed
        +-- config.py (stub)
        +-- logging.py (stub)
        +-- errors.py (stub)
```

### Recommended Project Structure
```
fs-monorepo/
├── pyproject.toml           # Single source of truth for build, deps, tools
├── README.md                # Existing
├── src/
│   ├── banking_client/
│   │   ├── __init__.py      # Docstring + __version__
│   │   └── py.typed         # PEP 561 marker
│   ├── mcp_server/
│   │   ├── __init__.py      # Docstring + __version__
│   │   └── py.typed
│   ├── agent/
│   │   ├── __init__.py      # Docstring + __version__
│   │   └── py.typed
│   └── common/
│       ├── __init__.py      # Docstring + __version__ + __all__ + re-exports
│       ├── py.typed
│       ├── config.py        # Stub with type annotations
│       ├── logging.py       # Stub with type annotations
│       └── errors.py        # Stub with type annotations
└── tests/                   # Empty for now (Phase 2 adds trivial test)
```

### Pattern 1: Skeleton `__init__.py` with Dynamic Version
**What:** Each package's `__init__.py` reads its version from installed package metadata using the project distribution name, not `__name__`.
**When to use:** All four packages in this phase.
**Critical detail:** Since this is a single project with one `pyproject.toml`, the distribution name is the *project* name (e.g., `open-banking-mcp`), not the individual package names. All four packages share the same version from the same distribution. `importlib.metadata.version("banking_client")` would raise `PackageNotFoundError` because `banking_client` is not a distribution -- it is a package within the `open-banking-mcp` distribution. [ASSUMED]
**Example:**
```python
# Source: docs.python.org/3/library/importlib.metadata.html + websearch verification
"""Banking client package for Open Banking MCP."""

import importlib.metadata

try:
    __version__: str = importlib.metadata.version("open-banking-mcp")
except importlib.metadata.PackageNotFoundError:
    __version__: str = "0.0.0"
```

### Pattern 2: Stub Module with Type Annotations and Google Docstrings
**What:** Stub files in `common/` with full type annotations, Google-style docstrings, and no implementation.
**When to use:** `common/config.py`, `common/logging.py`, `common/errors.py` (per D-01, D-02).
**Example:**
```python
# Source: Synthesized from D-01, D-02, ruff D rules documentation
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

### Pattern 3: Convenience Re-exports in `common/__init__.py`
**What:** `common/__init__.py` re-exports key symbols via `__all__` so downstream packages can do `from common import OpenBankingError`.
**When to use:** `common/__init__.py` (per D-03).
**Example:**
```python
# Source: D-03 decision + Python packaging conventions
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
```

### Pattern 4: Hatchling Multi-Package Configuration
**What:** Explicitly listing multiple packages under `src/` in `[tool.hatch.build.targets.wheel]`.
**When to use:** The `pyproject.toml` build configuration.
**Example:**
```toml
# Source: hatch.pypa.io/latest/config/build/#packages
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = [
    "src/banking_client",
    "src/mcp_server",
    "src/agent",
    "src/common",
]
```

### Anti-Patterns to Avoid
- **Using `__name__` with `importlib.metadata.version()`:** In a multi-package single-project setup, `__name__` resolves to the package name (e.g., `banking_client`), not the distribution name. This will raise `PackageNotFoundError`. Use the project name string literal instead. [ASSUMED]
- **Omitting `packages` from hatchling config:** Hatchling's auto-discovery may not find all four packages under `src/` -- always list them explicitly. [CITED: hatch.pypa.io/latest/config/build]
- **Naming a module `logging.py` without care:** `common/logging.py` shadows the stdlib `logging` module within the `common` package scope. Inside `common/logging.py`, use `import logging as _stdlib_logging` or `from __future__ import annotations` and avoid bare `import logging` to prevent circular reference issues. [ASSUMED]
- **Missing `from __future__ import annotations`:** Without this import, union types using `X | Y` syntax require Python 3.10+ at runtime. While Python 3.12 supports this natively, including the import is a best practice for forward-compatibility. [ASSUMED]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Version string | Hard-coded `__version__ = "0.1.0"` in each file | `importlib.metadata.version()` from pyproject.toml | Single source of truth; no sync drift between pyproject.toml and code |
| Import sorting | Manual import ordering | ruff's I (isort) rules | Automated, consistent, CI-enforceable |
| Code formatting | Manual formatting | ruff format | Deterministic, no style debates |
| Docstring validation | Manual review | ruff's D rules with Google convention | Automated enforcement of consistent docstring style |

**Key insight:** This phase is entirely about configuration and scaffolding. Every tool choice is locked by user decisions. The complexity is in getting all the configuration sections to work together in a single `pyproject.toml` without conflicts.

## Common Pitfalls

### Pitfall 1: importlib.metadata.version() with Wrong Distribution Name
**What goes wrong:** Calling `importlib.metadata.version("banking_client")` raises `PackageNotFoundError` because the installed distribution is `open-banking-mcp`, not `banking_client`.
**Why it happens:** A single `pyproject.toml` creates a single distribution. Individual packages under `src/` are not separate distributions.
**How to avoid:** Use the literal project name from `pyproject.toml`'s `[project] name` field in all `importlib.metadata.version()` calls.
**Warning signs:** `PackageNotFoundError` at import time even after `uv sync`. [ASSUMED]

### Pitfall 2: mypy Not Finding Packages in src/ Layout
**What goes wrong:** `mypy --strict src/` reports "Cannot find implementation or library stub" errors.
**Why it happens:** mypy needs to know the source root to resolve imports. Without `mypy_path` configuration, it cannot find packages under `src/`.
**How to avoid:** Set `mypy_path = "$MYPY_CONFIG_FILE_DIR/src"` in `[tool.mypy]` or list explicit packages.
**Warning signs:** Import errors from mypy on cross-package imports (e.g., `from common import ...`). [CITED: mypy.readthedocs.io/en/stable/config_file.html]

### Pitfall 3: Ruff D Rules Requiring Docstrings Everywhere
**What goes wrong:** `ruff check` fails with D100/D101/D103 errors on every module, class, and function.
**Why it happens:** When `D` rules are selected, ruff requires docstrings on all public modules, classes, and functions.
**How to avoid:** Ensure every `__init__.py` has a module docstring. All public functions in stub files must have Google-style docstrings. Use `per-file-ignores` for test files if needed.
**Warning signs:** Dozens of D1xx violations on first run. [CITED: docs.astral.sh/ruff/settings]

### Pitfall 4: `common/logging.py` Shadowing stdlib
**What goes wrong:** Code inside `common/logging.py` that tries `import logging` gets a circular import.
**Why it happens:** Python's import system resolves `logging` to the current package's `logging.py` before looking at stdlib.
**How to avoid:** Inside `common/logging.py`, never do bare `import logging`. Use the full module path or alias. When other code in `common/` needs stdlib logging, use `import logging` before importing from `common.logging`.
**Warning signs:** `ImportError` or `AttributeError` when accessing stdlib logging attributes. [ASSUMED]

### Pitfall 5: Hatchling Not Discovering All Packages
**What goes wrong:** After `uv sync`, some packages are not importable.
**Why it happens:** Hatchling's auto-discovery may only find one package under `src/` when multiple exist.
**How to avoid:** Always explicitly list packages in `[tool.hatch.build.targets.wheel] packages = [...]`.
**Warning signs:** `ModuleNotFoundError` for some but not all packages after install. [CITED: hatch.pypa.io/latest/config/build]

## Code Examples

Verified patterns from official sources:

### Complete pyproject.toml Structure
```toml
# Source: Synthesized from hatch.pypa.io, mypy docs, ruff docs, pytest-asyncio docs
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "open-banking-mcp"
version = "0.1.0"
description = "Open Banking MCP Capstone"
requires-python = ">=3.12"
dependencies = [
    "mcp>=1.27,<2",
]

[project.optional-dependencies]
dev = [
    "mypy>=1.16",
    "ruff>=0.11",
    "pytest>=8",
    "pytest-asyncio>=1",
    "pytest-cov>=7",
]

[tool.hatch.build.targets.wheel]
packages = [
    "src/banking_client",
    "src/mcp_server",
    "src/agent",
    "src/common",
]

[tool.mypy]
strict = true
python_version = "3.12"
mypy_path = "$MYPY_CONFIG_FILE_DIR/src"
packages = [
    "banking_client",
    "mcp_server",
    "agent",
    "common",
]

[tool.ruff]
target-version = "py312"
line-length = 120
src = ["src"]

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM", "D"]

[tool.ruff.lint.pydocstyle]
convention = "google"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

### Minimal __init__.py for mcp_server and agent (D-10, D-11)
```python
# Source: D-10, D-11, docs.python.org/3/library/importlib.metadata.html
"""MCP server package for Open Banking MCP."""

import importlib.metadata

try:
    __version__: str = importlib.metadata.version("open-banking-mcp")
except importlib.metadata.PackageNotFoundError:
    __version__ = "0.0.0"
```

### common/errors.py Stub (D-01, D-02)
```python
# Source: D-01, D-02 decisions
"""Custom error types for Open Banking MCP."""

from __future__ import annotations


class OpenBankingError(Exception):
    """Base exception for all Open Banking MCP errors."""


class ConfigurationError(OpenBankingError):
    """Raised when a required configuration value is missing or invalid."""


class AuthenticationError(OpenBankingError):
    """Raised when authentication with the FDX API fails."""
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| setup.py + setup.cfg | pyproject.toml (PEP 621) | 2022+ | Single declarative config file |
| setuptools for src-layout | hatchling | 2022+ | Near-zero config for src layout |
| black + isort + flake8 | ruff (lint + format) | 2023+ | Single fast tool, fewer deps |
| pip + venv | uv | 2024+ | 10-100x faster dependency resolution |
| Hard-coded __version__ | importlib.metadata.version() | Python 3.8+ | No version string duplication |

**Deprecated/outdated:**
- `setup.py` / `setup.cfg`: Replaced by `pyproject.toml` as the standard [ASSUMED]
- `black` + `isort` as separate tools: ruff format replaces both [ASSUMED]
- `flake8` for linting: ruff check is a drop-in replacement with better performance [ASSUMED]

## Assumptions Log

> List all claims tagged `[ASSUMED]` in this research. The planner and discuss-phase use this
> section to identify decisions that need user confirmation before execution.

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `importlib.metadata.version()` must use the project distribution name ("open-banking-mcp"), not the package name (`__name__`) | Pitfall 1, Pattern 1 | `PackageNotFoundError` at import time; easy to fix by changing the string literal |
| A2 | `common/logging.py` can shadow stdlib `logging` if not handled carefully | Pitfall 4, Anti-Patterns | Circular import at runtime; can be fixed with import aliasing |
| A3 | `from __future__ import annotations` is best practice even on Python 3.12+ | Anti-Patterns | No functional impact on 3.12+; purely stylistic preference |
| A4 | pytest is de facto standard for Python testing | Standard Stack | Zero risk -- universally agreed |
| A5 | uv is fast modern replacement for pip/venv | Standard Stack | Zero risk -- user already chose uv |
| A6 | setup.py/setup.cfg deprecated in favor of pyproject.toml | State of the Art | Low risk -- PEP 621 is official standard |
| A7 | The project name in pyproject.toml should be "open-banking-mcp" or similar | Code Examples | User may prefer a different project name; change string literal accordingly |

## Open Questions

1. **Project distribution name**
   - What we know: The `pyproject.toml` `[project] name` field determines the distribution name used by `importlib.metadata.version()`.
   - What's unclear: The exact project name has not been explicitly stated (e.g., "open-banking-mcp" vs "fs-monorepo" vs something else).
   - Recommendation: Use `"open-banking-mcp"` as a sensible default matching the capstone name. This can be changed easily. The planner should use this name unless the user specifies otherwise.

2. **Dev dependency group style**
   - What we know: `uv` supports both `[project.optional-dependencies]` and `[dependency-groups]` (PEP 735).
   - What's unclear: Whether to use `[project.optional-dependencies] dev = [...]` or `[dependency-groups] dev = [...]`.
   - Recommendation: Use `[dependency-groups]` if the uv version supports it (0.9+ does). This is the newer standard for development dependencies. Either approach works. [ASSUMED]

3. **Initial project version**
   - What we know: `pyproject.toml` needs a `version` field.
   - What's unclear: Whether to start at `0.1.0` or `0.0.1`.
   - Recommendation: Use `"0.1.0"` as a conventional starting version for a project with defined structure.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| uv | Package management, `uv sync` | Yes | 0.9.20 | -- |
| Python 3.12 | Runtime, type checking target | Yes | 3.12.12 | -- |
| Python 3.13 | CI matrix (Phase 2) | No (downloadable via uv) | -- | `uv python install 3.13` |
| mypy | Type checking | No (installed via uv sync) | -- | Installed as dev dependency |
| ruff | Linting/formatting | No (installed via uv sync) | -- | Installed as dev dependency |
| pytest | Testing | No (installed via uv sync) | -- | Installed as dev dependency |

**Missing dependencies with no fallback:**
- None -- all tools are installed via `uv sync` from dev dependencies.

**Missing dependencies with fallback:**
- Python 3.13 not locally installed but available via `uv python install 3.13` (needed for Phase 2 CI, not this phase).

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A -- no auth logic in skeleton |
| V3 Session Management | No | N/A -- no sessions in skeleton |
| V4 Access Control | No | N/A -- no access control in skeleton |
| V5 Input Validation | No | N/A -- no input handling in skeleton |
| V6 Cryptography | No | N/A -- no crypto in skeleton |

### Known Threat Patterns for Python Packaging

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Dependency confusion / typosquatting | Tampering | Pin exact versions in lock file; use `uv.lock` |
| Malicious postinstall scripts | Elevation | Verify package legitimacy before adding to deps |
| Supply chain via build backend | Tampering | Use PyPA-maintained hatchling; verify source |

**Note:** This phase has minimal security surface -- it is scaffolding only. The `mcp` dependency is pinned but unused. Security becomes relevant in Phase 2+ when actual code is implemented.

## Project Constraints (from CLAUDE.md)

- **Tech stack**: Python 3.12+, `uv`, `ruff`, `mypy --strict`, `pytest`, `hatchling` build backend
- **Compatibility**: CI must pass on both Python 3.12 and 3.13 (Phase 2, not this phase)
- **Dependencies**: `mcp>=1.27,<2` locked now even though unused
- **Quality**: 80% coverage gate enforced in CI (Phase 2); pre-commit must mirror CI checks (Phase 2)
- **Scope**: No business logic -- package skeletons only
- **GSD Workflow**: All edits must go through GSD workflow commands

## Sources

### Primary (HIGH confidence)
- [PyPI registry](https://pypi.org) -- verified all package versions and availability (2026-06-24)

### Secondary (MEDIUM confidence)
- [Hatch build configuration](https://hatch.pypa.io/latest/config/build/) -- packages option for src-layout
- [Mypy configuration](https://mypy.readthedocs.io/en/stable/config_file.html) -- strict mode, mypy_path, packages
- [Ruff configuration](https://docs.astral.sh/ruff/configuration/) -- rule selection, target-version
- [Ruff pydocstyle settings](https://docs.astral.sh/ruff/settings/#lintpydocstyleconvention) -- convention = "google"
- [Ruff src setting](https://docs.astral.sh/ruff/settings/#src) -- source roots for import sorting
- [pytest-asyncio configuration](https://pytest-asyncio.readthedocs.io/en/latest/reference/configuration.html) -- asyncio_mode = "auto"
- [Python importlib.metadata](https://docs.python.org/3/library/importlib.metadata.html) -- version() API

### Tertiary (LOW confidence)
- WebSearch results for importlib.metadata patterns -- common usage patterns
- WebSearch results for PEP 561 py.typed markers -- file placement conventions

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all packages verified on PyPI, versions confirmed, well-established ecosystem tools
- Architecture: HIGH -- src-layout with hatchling is well-documented and standard; multi-package config verified via official docs
- Pitfalls: MEDIUM -- most pitfalls are from training knowledge and common patterns, not verified against this exact project configuration

**Research date:** 2026-06-24
**Valid until:** 2026-07-24 (stable ecosystem, 30-day validity)
