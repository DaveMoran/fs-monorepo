---
phase: 02-ci-hooks-docs-verification
reviewed: 2026-06-25T10:45:00Z
depth: standard
files_reviewed: 4
files_reviewed_list:
  - .github/workflows/ci.yml
  - .pre-commit-config.yaml
  - pyproject.toml
  - tests/test_common.py
findings:
  critical: 1
  warning: 2
  info: 1
  total: 4
status: issues_found
---

# Phase 02: Code Review Report

**Reviewed:** 2026-06-25T10:45:00Z
**Depth:** standard
**Files Reviewed:** 4
**Status:** issues_found

## Summary

Phase 02 adds a GitHub Actions CI workflow (lint, type-check, test with coverage), pre-commit hooks (ruff + mypy), coverage configuration in pyproject.toml, and a smoke test for common/banking_client stubs. The CI structure is solid — parallel jobs, matrix strategy, uv caching. One critical finding: the mypy pre-commit hook passes filenames by default, causing divergent behavior from CI. Two warnings on CI robustness. Test file is clean.

## Critical Issues

### CR-01: Mypy pre-commit hook passes filenames, diverging from CI

**File:** `.pre-commit-config.yaml:9-16`
**Issue:** The mypy local hook has `types: [python]` but does not set `pass_filenames: false`. By default, pre-commit passes staged filenames as arguments to the hook entry command, running `uv run mypy <file1.py> <file2.py>`. When mypy receives explicit file arguments, it ignores the `packages` setting from `[tool.mypy]` in pyproject.toml and does not apply the configured `mypy_path`. This means: (1) pre-commit mypy checks only staged files, not the full package graph — cross-module type errors are silently skipped; (2) mypy may fail to resolve imports because `mypy_path = "$MYPY_CONFIG_FILE_DIR/src"` is not used when files are passed directly. CI runs `uv run mypy` with no arguments, which respects the `packages` and `mypy_path` config. The pre-commit hook and CI will produce different results.

**Fix:**
```yaml
  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: uv run mypy
        language: system
        types: [python]
        require_serial: true
        pass_filenames: false
```

## Warnings

### WR-01: CI lint job does not pin Python version

**File:** `.github/workflows/ci.yml:10-19`
**Issue:** The `lint` job does not pass `python-version` to `astral-sh/setup-uv`, unlike `type-check` and `test` which use a 3.12/3.13 matrix. While ruff itself is a Rust binary and version-independent, `uv sync` needs a Python interpreter to create the virtualenv and resolve dependencies. Without pinning, the lint job uses whatever default Python `setup-uv` or ubuntu-latest provides. If ubuntu-latest changes its default Python (as has happened historically), `uv sync` could fail or pick a version outside `requires-python = ">=3.12"`. This is also an inconsistency with the other two jobs.

**Fix:**
```yaml
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true
          python-version: "3.13"
      - run: uv sync --all-extras --dev
      - run: uv run ruff check .
      - run: uv run ruff format --check .
```

### WR-02: Dev dependencies split across two mechanisms

**File:** `pyproject.toml:14-21,67-69`
**Issue:** Development dependencies are split between `[project.optional-dependencies] dev` (mypy, ruff, pytest, etc.) and `[dependency-groups] dev` (pre-commit). PEP 735 dependency groups and optional-dependencies are different mechanisms with different semantics. `uv sync --all-extras --dev` installs both, but: (1) contributors must know to use both flags, not just `--dev` or `--all-extras` alone; (2) `pip install -e ".[dev]"` (a common contributor workflow) would miss pre-commit entirely since it only sees optional-dependencies; (3) having two `dev` groups in different sections invites confusion when adding future dev tools. Consider consolidating into one mechanism.

**Fix:** Move `pre-commit` into `[project.optional-dependencies] dev` alongside the other dev tools, or move everything into `[dependency-groups]`:
```toml
[project.optional-dependencies]
dev = [
    "mypy>=1.16",
    "ruff>=0.11",
    "pytest>=8",
    "pytest-asyncio>=1",
    "pytest-cov>=7",
    "pre-commit>=4.6.0",
]
```

## Info

### IN-01: Pre-commit ruff-check uses `--fix` which auto-modifies staged files

**File:** `.pre-commit-config.yaml:4-5`
**Issue:** The `ruff-check` hook passes `args: [--fix]`, which auto-fixes lint issues by modifying working-tree files. This is the documented recommended pattern from `astral-sh/ruff-pre-commit` and most teams prefer it. However, it means a pre-commit run can silently modify files, requiring the developer to re-stage. If the team prefers a "fail and report" workflow instead, remove `--fix`. Noting for awareness — not a defect.

**Fix:** No change needed if auto-fix is desired. To switch to report-only: `args: []` (or remove `args` entirely).

---

_Reviewed: 2026-06-25T10:45:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
