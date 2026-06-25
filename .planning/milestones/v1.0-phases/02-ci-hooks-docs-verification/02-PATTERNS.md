# Phase 2: CI, Hooks, Docs & Verification - Pattern Map

**Mapped:** 2026-06-25
**Files analyzed:** 8
**Analogs found:** 3 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `.github/workflows/ci.yml` | config | event-driven | None | no-analog |
| `.pre-commit-config.yaml` | config | event-driven | None | no-analog |
| `tests/test_common.py` | test | request-response | None (first test) | no-analog |
| `CONTRIBUTING.md` | docs | N/A | `README.md` | partial |
| `LICENSE` | docs | N/A | None | no-analog |
| `.env.example` | config | N/A | None | no-analog |
| `README.md` (modify) | docs | N/A | `README.md` (existing) | exact |
| `pyproject.toml` (modify) | config | N/A | `pyproject.toml` (existing) | exact |

## Pattern Assignments

### `tests/test_common.py` (test, request-response)

**Analog:** No existing test files. First test in the project.

**Test targets (what the test must import and exercise):**

`src/common/__init__.py` (lines 1-15) — exports to verify:
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

`src/common/config.py` (lines 1-17) — function signature:
```python
def get_config(key: str, default: str | None = None) -> str | None:
    """Retrieve a configuration value by key."""
    return default
```

`src/common/errors.py` (lines 1-15) — class hierarchy:
```python
class OpenBankingError(Exception):
    """Base exception for all Open Banking MCP errors."""

class ConfigurationError(OpenBankingError):
    """Raised when a required configuration value is missing or invalid."""

class AuthenticationError(OpenBankingError):
    """Raised when authentication with the FDX API fails."""
```

`src/common/logging.py` (lines 1-17) — function signature:
```python
def get_logger(name: str) -> _stdlib_logging.Logger:
    """Create a configured logger instance."""
    return _stdlib_logging.getLogger(name)
```

**Test pattern conventions to follow:**
- Use `from __future__ import annotations` consistent with source modules
- Type-annotate test return as `-> None` (mypy --strict requires this)
- Google-style docstrings for test module (ruff D rules enabled)
- Imports use package names directly (e.g., `from common.config import get_config`) since `src/` is in the Python path via hatchling and mypy_path config

---

### `pyproject.toml` (modify — add coverage config)

**Analog:** `pyproject.toml` (existing, lines 1-54)

**Existing tool config pattern** (lines 31-54) — all tool sections follow `[tool.X]` convention:
```toml
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

**New sections to add** (append after existing tool config):
```toml
[tool.coverage.run]
source = ["src"]
omit = [
    "src/mcp_server/*",
    "src/agent/*",
]

[tool.coverage.report]
show_missing = true
```

---

### `README.md` (modify — replace placeholder)

**Analog:** `README.md` (existing, line 1):
```markdown
# fs-monorepo
```

This is a single-line placeholder. The modification replaces it entirely with a structured README per D-10 (CI badge, project description, quick start, development setup, architecture overview).

---

### `.github/workflows/ci.yml` (config, event-driven)

**Analog:** None — no GitHub Actions workflows exist in the project.

**Use RESEARCH.md patterns directly.** Key structural decisions from CONTEXT.md:
- D-01: Trigger on push to `main` and PRs targeting `main`
- D-02: Workflow named `CI`
- D-03: Lint, type-check, and test as separate parallel jobs
- D-04: Cache uv dependencies via `enable-cache: true`
- Lint job: no Python matrix (ruff is Python-version-independent per RESEARCH.md Open Question 1)
- Type-check job: Python 3.12/3.13 matrix
- Test job: Python 3.12/3.13 matrix, `uv run pytest --cov`, then separate `coverage report --fail-under=80` step (D-13)
- Include `ruff format --check` in lint job (per RESEARCH.md Open Question 2)

---

### `.pre-commit-config.yaml` (config, event-driven)

**Analog:** None — no pre-commit configuration exists.

**Use RESEARCH.md patterns directly.** Key structural decisions from CONTEXT.md:
- D-05: Run ruff (lint + format) and mypy only; no tests
- D-06: Use `astral-sh/ruff-pre-commit` for ruff hooks
- D-07: Mypy as local hook (`language: system`) with `entry: uv run mypy`

---

### `CONTRIBUTING.md` (docs)

**Analog:** `README.md` — partial match (both are project documentation files).

The only existing documentation pattern is the single-line `README.md`. No structural analog exists for a full contributor guide. This is a net-new file per D-08 (full workflow guide: setup instructions, PR workflow, commit conventions, code style).

**Convention from CONTEXT.md to embed:**
- D-09: Conventional Commits (`feat:`, `fix:`, `docs:`, `chore:`)
- Reference `uv` for setup, `pre-commit install` for hooks
- Reference ruff + mypy as quality gates

---

### `LICENSE` (docs)

**Analog:** None — no license file exists. Standard MIT license text with copyright year 2025 and holder name.

---

### `.env.example` (config)

**Analog:** None — no environment config files exist. Per CONF-01, document FDX base URL and auth stub key placeholders.

## Shared Patterns

### Module Import Convention
**Source:** `src/common/__init__.py` (lines 1-15), `src/banking_client/__init__.py` (lines 1-9)
**Apply to:** `tests/test_common.py`

All packages use direct package-name imports (not `src.` prefixed). The `src/` directory is configured as the source root in both hatchling (`packages = ["src/banking_client", ...]`) and mypy (`mypy_path = "$MYPY_CONFIG_FILE_DIR/src"`).

```python
from common import OpenBankingError, __version__
from common.config import get_config
from common.errors import AuthenticationError, ConfigurationError
from common.logging import get_logger
```

### Type Annotation Convention
**Source:** `src/common/config.py` (line 6), `src/common/logging.py` (line 8)
**Apply to:** `tests/test_common.py`

All functions use `from __future__ import annotations` and full type annotations. Under `mypy --strict`, test functions must be annotated with `-> None`.

```python
from __future__ import annotations

def test_version_is_string() -> None:
    assert isinstance(__version__, str)
```

### Docstring Convention
**Source:** `src/common/config.py` (lines 7-15), `src/common/errors.py` (lines 6-14)
**Apply to:** All new `.py` files

Google-style docstrings enforced by ruff rule `D` with `convention = "google"`. Module-level docstrings required. Function docstrings use `Args:` / `Returns:` sections.

```python
"""Configuration management for Open Banking MCP."""
```

### Tool Configuration Single Source of Truth
**Source:** `pyproject.toml` (lines 31-54)
**Apply to:** `.github/workflows/ci.yml`, `.pre-commit-config.yaml`

All tool configuration lives in `pyproject.toml`. CI steps and pre-commit hooks invoke tools without passing config flags — tools read from `pyproject.toml` automatically:
- `uv run ruff check .` (not `ruff check --select E,F,I,...`)
- `uv run mypy` (not `mypy --strict`)
- `uv run pytest --cov` (pytest reads `testpaths` and `asyncio_mode` from pyproject.toml)

## No Analog Found

Files with no close match in the codebase (planner should use RESEARCH.md patterns instead):

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `.github/workflows/ci.yml` | config | event-driven | No GitHub Actions workflows exist in the project |
| `.pre-commit-config.yaml` | config | event-driven | No pre-commit config exists in the project |
| `tests/test_common.py` | test | request-response | No test files exist yet (first test) |
| `CONTRIBUTING.md` | docs | N/A | No contributor documentation exists |
| `LICENSE` | docs | N/A | No license file exists |
| `.env.example` | config | N/A | No environment config templates exist |

All six net-new files have comprehensive patterns and code examples in RESEARCH.md (Code Examples section). The planner should reference those directly.

## Metadata

**Analog search scope:** Project root and `src/` directory
**Files scanned:** 14 source files
**Pattern extraction date:** 2026-06-25
