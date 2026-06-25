---
phase: 02-ci-hooks-docs-verification
plan: 01
subsystem: testing, infra
tags: [pytest, coverage, github-actions, ci, ruff, mypy]

requires:
  - phase: 01-package-skeleton-tooling
    provides: src-layout with banking_client, common, mcp_server, agent packages; pyproject.toml with ruff/mypy/pytest config
provides:
  - pytest test suite exercising common/ stubs with 83% coverage
  - coverage configuration measuring only real-code packages (banking_client, common)
  - GitHub Actions CI workflow with lint, type-check, test jobs on Python 3.12/3.13 matrix
affects: [02-02-pre-commit-hooks-docs]

tech-stack:
  added: [pytest-cov, coverage]
  patterns: [coverage omit for empty packages, separate coverage enforcement step in CI]

key-files:
  created:
    - tests/test_common.py
    - .github/workflows/ci.yml
  modified:
    - pyproject.toml

key-decisions:
  - "Coverage omit excludes mcp_server and agent (empty skeleton packages) to measure only real code (D-11)"
  - "Coverage gate is a separate CI step (coverage report --fail-under=80), not a pytest flag (D-13)"
  - "Lint job has no Python matrix; type-check and test jobs have 3.12/3.13 matrix"
  - "Added banking_client version test to reach 83% coverage (Rule 3: 80% gate would fail without it)"

patterns-established:
  - "Test files use from __future__ import annotations and -> None return annotations for mypy --strict"
  - "Tests import via package names (from common.config import get_config), not src-prefixed"
  - "CI tools read config from pyproject.toml; no CLI flags duplicated in workflow steps"

requirements-completed: [TEST-01, CI-01, CI-02, CI-03, CI-04]

coverage:
  - id: D1
    description: "pytest test suite with 5 tests exercising common/ and banking_client/ stubs, all passing"
    requirement: "TEST-01"
    verification:
      - kind: unit
        ref: "tests/test_common.py#test_version_is_string"
        status: pass
      - kind: unit
        ref: "tests/test_common.py#test_get_config_returns_default"
        status: pass
      - kind: unit
        ref: "tests/test_common.py#test_get_logger_returns_logger"
        status: pass
      - kind: unit
        ref: "tests/test_common.py#test_error_hierarchy"
        status: pass
      - kind: unit
        ref: "tests/test_common.py#test_banking_client_version_is_string"
        status: pass
    human_judgment: false
  - id: D2
    description: "Coverage config measures only banking_client and common, 80% gate passes (83% actual)"
    requirement: "CI-04"
    verification:
      - kind: integration
        ref: "uv run pytest --cov && uv run coverage report --fail-under=80"
        status: pass
    human_judgment: false
  - id: D3
    description: "GitHub Actions CI workflow with lint/type-check/test parallel jobs and 3.12/3.13 matrix"
    requirement: "CI-01"
    verification:
      - kind: other
        ref: ".github/workflows/ci.yml YAML structure validation"
        status: pass
    human_judgment: true
    rationale: "CI workflow cannot be verified locally; requires push to GitHub to confirm runner execution"

duration: 4min
completed: 2026-06-25
status: complete
---

# Phase 02 Plan 01: CI Pipeline & Test Coverage Summary

**Pytest test suite with 83% coverage on real-code packages and GitHub Actions CI running ruff, mypy, and pytest on Python 3.12/3.13 matrix**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-25T14:12:12Z
- **Completed:** 2026-06-25T14:16:41Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- 5 unit tests exercising common/ and banking_client/ package stubs with 83% coverage
- Coverage configuration measuring only banking_client and common, excluding empty mcp_server and agent packages
- GitHub Actions CI workflow with three parallel jobs (lint, type-check, test), Python 3.12/3.13 matrix, uv caching, and separate 80% coverage enforcement step

## Task Commits

Each task was committed atomically:

1. **Task 1: Add failing trivial test exercising common/ stubs** - `3d0c092` (test)
2. **Task 2: Add coverage config measuring only real-code packages** - `649bee7` (feat)
3. **Task 3: Add GitHub Actions CI workflow with matrix and parallel jobs** - `ae679dc` (feat)

## Files Created/Modified

- `tests/test_common.py` - 5 unit tests for common/ and banking_client/ stubs
- `pyproject.toml` - Added [tool.coverage.run] and [tool.coverage.report] sections
- `.github/workflows/ci.yml` - CI workflow with lint, type-check, test jobs

## Decisions Made

- Coverage omit excludes mcp_server and agent packages (D-11) -- they have no real code yet
- Coverage gate is a separate CI step using `coverage report --fail-under=80` (D-13), not a pytest flag
- Lint job runs without Python version matrix (ruff is Python-version-independent)
- Added banking_client version test to clear the 80% gate (Rule 3 deviation)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added banking_client test to reach 80% coverage threshold**
- **Found during:** Task 2 (coverage config)
- **Issue:** With only common/ tests, coverage was 70% (banking_client/__init__.py at 0%), failing the 80% gate
- **Fix:** Added `test_banking_client_version_is_string` test and banking_client import, raising coverage to 83%
- **Files modified:** tests/test_common.py
- **Verification:** `uv run coverage report --fail-under=80` exits 0 (83% total)
- **Committed in:** 649bee7 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking)
**Impact on plan:** Essential for the 80% gate to pass. The banking_client stub is structurally identical to common's and needs coverage.

## Issues Encountered

None

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- CI pipeline is ready; pushing to GitHub on main or via PR will trigger the full lint/type-check/test matrix
- Plan 02 (pre-commit hooks, docs) can proceed -- all CI infrastructure is in place
- Pre-commit hooks should mirror CI checks (ruff, mypy) as specified in the phase plan

---
*Phase: 02-ci-hooks-docs-verification*
*Completed: 2026-06-25*
