---
phase: 01-package-skeleton-tooling
plan: 01
subsystem: infra
tags: [python, hatchling, mypy, ruff, pytest, uv, src-layout]

requires:
  - phase: none
    provides: first phase — no prior dependencies
provides:
  - four-package src-layout skeleton (banking_client, mcp_server, agent, common)
  - pyproject.toml with hatchling build backend, strict mypy/ruff/pytest config
  - uv.lock for reproducible dependency resolution
  - common stubs (errors.py, config.py, logging.py) with type annotations
affects: [02-ci-hooks-docs-verification]

tech-stack:
  added: [hatchling, mypy, ruff, pytest, pytest-asyncio, pytest-cov, mcp]
  patterns: [src-layout multi-package, importlib.metadata dynamic version, py.typed PEP 561]

key-files:
  created:
    - pyproject.toml
    - uv.lock
    - src/banking_client/__init__.py
    - src/mcp_server/__init__.py
    - src/agent/__init__.py
    - src/common/__init__.py
    - src/common/errors.py
    - src/common/config.py
    - src/common/logging.py
  modified: []

key-decisions:
  - "Used importlib.metadata.version('open-banking-mcp') with PackageNotFoundError fallback for dynamic __version__"
  - "Annotate __version__ type only on first assignment branch to satisfy mypy --strict no-redef"
  - "Aliased stdlib logging as _stdlib_logging in common/logging.py to avoid shadow"

patterns-established:
  - "src-layout: all packages under src/ with explicit hatch.build.targets.wheel.packages"
  - "Type stubs: full annotations + Google-style docstrings on every public symbol"
  - "py.typed markers in every package root for PEP 561 compliance"

requirements-completed: [PKG-01, PKG-02, PKG-03, PKG-04, PKG-05, TOOL-01, TOOL-02, TOOL-03, TOOL-04, TOOL-05]

coverage:
  - id: D1
    description: "pyproject.toml with hatchling build backend, mcp pin, dev deps, and strict mypy/ruff/pytest config"
    requirement: "TOOL-01"
    verification:
      - kind: automated_ui
        ref: "python3 -c \"import tomllib; tomllib.load(open('pyproject.toml','rb'))\""
        status: pass
    human_judgment: false
  - id: D2
    description: "Four src-layout packages with typed __init__.py, py.typed markers, and common stubs"
    requirement: "PKG-01"
    verification:
      - kind: e2e
        ref: "uv run python -c \"import banking_client, mcp_server, agent, common; from common import OpenBankingError\""
        status: pass
    human_judgment: false
  - id: D3
    description: "mypy --strict src/ reports zero errors"
    requirement: "TOOL-02"
    verification:
      - kind: e2e
        ref: "uv run mypy --strict src/"
        status: pass
    human_judgment: false
  - id: D4
    description: "ruff check src/ and ruff format --check src/ report zero violations"
    requirement: "TOOL-03"
    verification:
      - kind: e2e
        ref: "uv run ruff check src/ && uv run ruff format --check src/"
        status: pass
    human_judgment: false
  - id: D5
    description: "uv sync completes and generates uv.lock for reproducible installs"
    requirement: "PKG-01"
    verification:
      - kind: e2e
        ref: "uv sync --extra dev"
        status: pass
    human_judgment: false

duration: 8min
completed: 2026-06-25
status: complete
---

# Phase 1: Package Skeleton & Tooling Summary

**Four-package src-layout skeleton with hatchling, strict mypy/ruff, and mcp pin — all quality gates green before any business logic**

## Performance

- **Duration:** 8 min
- **Started:** 2026-06-25T05:35:00Z
- **Completed:** 2026-06-25T05:55:00Z
- **Tasks:** 3
- **Files modified:** 16

## Accomplishments
- pyproject.toml with hatchling build backend, strict mypy/ruff/pytest config, and mcp>=1.27,<2 pin
- Four packages under src/ (banking_client, mcp_server, agent, common) with typed __init__.py and py.typed markers
- Common stubs: errors.py (OpenBankingError hierarchy), config.py (get_config), logging.py (get_logger with stdlib alias)
- uv sync + mypy --strict + ruff check + ruff format all pass green end-to-end

## Task Commits

Each task was committed atomically:

1. **Task 1: Create pyproject.toml** - `e05727b` (feat)
2. **Task 2: Create four src-layout packages** - `d561389` (feat)
3. **Task 3: Sync environment and fix mypy, prove all gates green** - `ce287c0` (fix)

## Files Created/Modified
- `pyproject.toml` - Build backend, deps, and tool config
- `uv.lock` - Resolved dependency lock file
- `src/banking_client/__init__.py` - Banking client package with dynamic version
- `src/banking_client/py.typed` - PEP 561 marker
- `src/mcp_server/__init__.py` - MCP server package with dynamic version
- `src/mcp_server/py.typed` - PEP 561 marker
- `src/agent/__init__.py` - Agent package with dynamic version
- `src/agent/py.typed` - PEP 561 marker
- `src/common/__init__.py` - Common utilities with OpenBankingError re-export
- `src/common/py.typed` - PEP 561 marker
- `src/common/errors.py` - OpenBankingError, ConfigurationError, AuthenticationError
- `src/common/config.py` - get_config stub with full type annotations
- `src/common/logging.py` - get_logger stub with stdlib alias to avoid shadow

## Decisions Made
- Used `importlib.metadata.version("open-banking-mcp")` with PackageNotFoundError fallback (distribution name, not package name)
- Fixed mypy no-redef by annotating __version__ type only on the first branch of try/except
- Aliased stdlib logging as `_stdlib_logging` in common/logging.py to avoid module shadow (Pitfall 4)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Correctness] Fixed mypy --strict no-redef errors**
- **Found during:** Task 3 (quality gate verification)
- **Issue:** Duplicate type annotation `__version__: str` on both try and except branches caused mypy no-redef errors in all 4 __init__.py files
- **Fix:** Removed type annotation from except branch (keep only on try branch)
- **Files modified:** src/banking_client/__init__.py, src/mcp_server/__init__.py, src/agent/__init__.py, src/common/__init__.py
- **Verification:** mypy --strict src/ reports 0 errors
- **Committed in:** ce287c0 (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 correctness)
**Impact on plan:** Fix was necessary for mypy --strict to pass green. No scope creep.

## Issues Encountered
None — all three quality gates (mypy, ruff check, ruff format) pass green.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Package skeleton complete, ready for Phase 2 (CI, Hooks, Docs & Verification)
- All local tooling verified: mypy --strict, ruff check/format, pytest config in place
- Phase 2 can add GitHub Actions CI, pre-commit hooks, contributor docs, and the trivial test

---
*Phase: 01-package-skeleton-tooling*
*Completed: 2026-06-25*
