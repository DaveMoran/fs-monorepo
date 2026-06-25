# Phase 2: CI, Hooks, Docs & Verification - Research

**Researched:** 2026-06-25
**Domain:** CI/CD, pre-commit hooks, developer documentation, test infrastructure
**Confidence:** MEDIUM

## Summary

Phase 2 layers GitHub Actions CI, pre-commit hooks, documentation, and a trivial test onto the Phase 1 skeleton. The domain is well-understood infrastructure work with mature, stable tooling. The primary complexity is ensuring CI jobs, pre-commit hooks, and pyproject.toml configuration all align — ruff, mypy, and pytest must read from the same config source with no duplication.

The coverage strategy requires careful attention: the user decided (D-11, D-13) to exclude intentionally empty packages (`mcp_server`, `agent`) from coverage measurement and to enforce the 80% gate as a separate CI step rather than via `--cov-fail-under`. This means using `[tool.coverage.run] source` and `[tool.coverage.run] omit` in pyproject.toml to measure only `banking_client` and `common`, and a post-test `coverage report --fail-under=80` step in CI.

**Primary recommendation:** All tool configuration stays in `pyproject.toml` as the single source of truth. CI jobs and pre-commit hooks invoke the same tools (`ruff check`, `mypy --strict`, `pytest --cov`) without duplicating rules or thresholds.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** CI triggers on push to `main` and PRs targeting `main` only
- **D-02:** Workflow named `CI`
- **D-03:** Lint, type-check, and test run as separate parallel jobs
- **D-04:** Cache `uv` dependencies between CI runs
- **D-05:** Pre-commit runs ruff (lint + format) and mypy. Tests are CI-only, not in pre-commit
- **D-06:** Ruff hooks use the official `astral-sh/ruff-pre-commit` repo
- **D-07:** Mypy runs as a local hook (`language: system`) using the project virtualenv
- **D-08:** CONTRIBUTING.md is a full workflow guide (2-3 pages, enterprise-grade)
- **D-09:** Conventional Commits enforced: `feat:`, `fix:`, `docs:`, `chore:` prefixes
- **D-10:** README.md structured with CI badge, project description, quick start, development setup, architecture overview
- **D-11:** Coverage excludes `mcp_server` and `agent` — only measure `banking_client` and `common`
- **D-12:** Trivial test targets `common/` module stubs (config, logging, errors)
- **D-13:** Coverage enforcement uses a separate CI step (not `--cov-fail-under`)

### Claude's Discretion
No areas deferred to Claude's discretion.

### Deferred Ideas (OUT OF SCOPE)
None.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CI-01 | GitHub Actions workflow runs on Python 3.12 and 3.13 matrix | setup-uv action with matrix strategy, verified patterns from official docs |
| CI-02 | CI runs `ruff check` (lint) | Lint job using `uv run ruff check .` in parallel job |
| CI-03 | CI runs `mypy --strict` type check | Type-check job using `uv run mypy` in parallel job |
| CI-04 | CI runs pytest with coverage, fails below 80% | Test job with `uv run pytest --cov` then separate `coverage report --fail-under=80` step |
| HOOK-01 | `.pre-commit-config.yaml` runs ruff lint + format hooks | `astral-sh/ruff-pre-commit` with `ruff-check` and `ruff-format` hook IDs |
| HOOK-02 | `.pre-commit-config.yaml` runs mypy hook mirroring CI | Local hook with `language: system`, entry `uv run mypy` |
| DOCS-01 | README.md includes capstone spec excerpt placeholder | Structured README with CI badge, description, quick start, architecture |
| DOCS-02 | LICENSE file contains MIT license | Standard MIT license text |
| DOCS-03 | CONTRIBUTING.md provides contributor guidance | Full workflow guide: setup, PR workflow, commit conventions, code style |
| CONF-01 | `.env.example` documents config vars | FDX base URL and auth stub key placeholders |
| TEST-01 | One trivial passing test proves pytest + coverage pipeline | Test imports from `common/` (config, logging, errors) to exercise stubs |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| CI pipeline | GitHub Actions (cloud) | -- | Workflow runs on GitHub-hosted runners, not local |
| Pre-commit hooks | Developer Machine | -- | Runs in local git hooks before commit |
| Coverage enforcement | GitHub Actions | -- | 80% gate is a CI-only concern per D-13 |
| Tool configuration | pyproject.toml (repo) | -- | Single source of truth for ruff, mypy, pytest, coverage |
| Documentation | Repository files | -- | README, CONTRIBUTING, LICENSE are static repo files |

## Standard Stack

### Core

| Library/Tool | Version | Purpose | Why Standard |
|-------------|---------|---------|--------------|
| `astral-sh/setup-uv` | v8.2.0 | GitHub Actions uv installer with caching | Official Astral action, built-in cache support [CITED: docs.astral.sh/uv/guides/integration/github/] |
| `actions/checkout` | v4 | Repository checkout in CI | Standard GitHub-maintained action [ASSUMED] |
| `astral-sh/ruff-pre-commit` | v0.15.19 | Pre-commit ruff hooks | Official Astral repo for ruff integration [CITED: github.com/astral-sh/ruff-pre-commit] |
| `pre-commit` | >=4.0 | Git hook framework | Industry standard for Python pre-commit hooks [ASSUMED] |
| `pytest-cov` | >=7 | Coverage measurement | Already in project dev deps (TOOL-04 from Phase 1) |
| `coverage` | (via pytest-cov) | Coverage reporting and enforcement | `coverage report --fail-under=80` for separate enforcement step |

### Supporting

| Library/Tool | Version | Purpose | When to Use |
|-------------|---------|---------|-------------|
| `pre-commit/pre-commit-hooks` | v5.0.0 | Standard file hygiene hooks | trailing-whitespace, end-of-file-fixer, check-yaml [ASSUMED] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `language: system` mypy hook | `pre-commit/mirrors-mypy` | mirrors-mypy runs in isolated env, needs `additional_dependencies` for every project dep — fragile and diverges from pyproject.toml config. `language: system` uses project venv directly. |
| Separate coverage step (D-13) | `--cov-fail-under` in pytest addopts | `--cov-fail-under` exits pytest with error, mixing test failures and coverage failures. Separate step enables future badge/report upload. |
| `uv run` for CI commands | Direct `ruff`, `mypy`, `pytest` | `uv run` ensures commands execute in the correct venv with all deps — no activation needed. |

**Installation:**
```bash
uv add --dev pre-commit
```

## Architecture Patterns

### System Architecture Diagram

```
Developer Workstation                    GitHub Actions (CI)
========================                 ========================

  git commit                              push/PR to main
      |                                       |
      v                                       v
  .git/hooks/pre-commit                   .github/workflows/ci.yml
      |                                       |
      v                                   +---+---+---+
  pre-commit run                          |   |   |   |
      |                                   v   v   v   v
  +---+---+                             lint type test
  |       |                             job  job  job
  v       v                              |    |    |
ruff    mypy                             |    |    +-> coverage report
check   (local,                          |    |        --fail-under=80
+format  uv run)                         |    |
                                         v    v
                                        ruff  mypy
                                        check --strict
```

### Recommended Project Structure (new files)
```
.github/
└── workflows/
    └── ci.yml               # CI workflow (D-02: named "CI")
.pre-commit-config.yaml      # Hook config (D-05, D-06, D-07)
.env.example                 # Config var documentation (CONF-01)
CONTRIBUTING.md              # Contributor guide (DOCS-03)
LICENSE                       # MIT license (DOCS-02)
tests/
└── test_common.py            # Trivial test (TEST-01)
```

### Pattern 1: Parallel CI Jobs with Shared Setup

**What:** Each quality check (lint, type-check, test) runs as an independent job with its own matrix entry, sharing a common setup pattern.
**When to use:** When you want per-check GitHub status indicators (D-03) and faster feedback on failures.
**Example:**
```yaml
# Source: docs.astral.sh/uv/guides/integration/github/
jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true
      - run: uv sync --all-extras --dev
      - run: uv run ruff check .

  type-check:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true
          python-version: ${{ matrix.python-version }}
      - run: uv sync --all-extras --dev
      - run: uv run mypy

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true
          python-version: ${{ matrix.python-version }}
      - run: uv sync --all-extras --dev
      - run: uv run pytest --cov
      - name: Enforce coverage threshold
        run: uv run coverage report --fail-under=80
```

### Pattern 2: Local Mypy Hook via `language: system`

**What:** Mypy runs through the project virtualenv so it sees installed deps (e.g., `mcp` types).
**When to use:** Any project where mypy needs access to installed third-party stubs or typed packages.
**Example:**
```yaml
# Source: jaredkhan.com/blog/mypy-pre-commit (pattern adapted for uv)
- repo: local
  hooks:
    - id: mypy
      name: mypy
      entry: uv run mypy
      language: system
      types: [python]
      require_serial: true
```

### Pattern 3: Coverage Source Configuration

**What:** Configure coverage to measure only packages with real code, excluding intentionally empty skeletons.
**When to use:** Projects with stub packages that would drag down coverage metrics.
**Example:**
```toml
# pyproject.toml additions
[tool.coverage.run]
source = ["src"]
omit = [
    "src/mcp_server/*",
    "src/agent/*",
]

[tool.coverage.report]
show_missing = true
```

### Anti-Patterns to Avoid

- **Duplicating ruff/mypy config in CI:** Never pass `--select` or `--strict` args in CI steps if `pyproject.toml` already configures them. The tools read `pyproject.toml` automatically.
- **Using `mirrors-mypy` with `additional_dependencies`:** Fragile — every new dependency requires manual hook update. Use `language: system` instead (D-07).
- **Putting `--cov-fail-under` in pytest addopts:** Mixes test failures with coverage failures, makes it impossible to generate a coverage report when below threshold. Use separate `coverage report` step (D-13).
- **Running pytest in pre-commit:** Tests belong in CI only (D-05). Pre-commit should be fast — lint and type-check only.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Git hook management | Shell scripts in `.git/hooks/` | `pre-commit` framework | Version-pinned hooks, team-consistent, auto-installs |
| Ruff pre-commit integration | Custom local ruff hook | `astral-sh/ruff-pre-commit` | Official, versioned, handles both check and format |
| CI Python/uv setup | Manual `pip install uv` | `astral-sh/setup-uv` action | Handles caching, PATH, version pinning |
| Coverage threshold check | Custom script parsing coverage output | `coverage report --fail-under=80` | Built-in to coverage.py, standard exit code |
| MIT license text | Writing from memory | Standard MIT template | Copyright year and holder must be exact |

**Key insight:** Every tool in this phase has an official, maintained integration point. Hand-rolling any of them adds maintenance burden and divergence risk.

## Common Pitfalls

### Pitfall 1: Mypy Can't Find Installed Packages in Pre-commit
**What goes wrong:** `mirrors-mypy` runs mypy in an isolated virtualenv that doesn't have `mcp` or other project deps installed. Mypy reports `Cannot find implementation or library stub for module named "mcp"`.
**Why it happens:** Pre-commit creates isolated envs per hook by default. `additional_dependencies` in the hook config is the escape hatch, but it's manual and fragile.
**How to avoid:** Use `language: system` with `entry: uv run mypy` (D-07). This runs mypy in the project's virtualenv where all deps are installed.
**Warning signs:** Mypy errors mentioning missing stubs or modules that are clearly in `pyproject.toml` dependencies.

### Pitfall 2: Coverage Measures Wrong Packages
**What goes wrong:** Without explicit `source` and `omit` config, coverage measures all code under `src/`, including empty `__init__.py` files in `mcp_server` and `agent`. These either inflate or deflate the number depending on whether the trivial test imports them.
**Why it happens:** pytest-cov defaults to measuring everything that gets imported during the test run.
**How to avoid:** Set `[tool.coverage.run] source = ["src"]` with `omit = ["src/mcp_server/*", "src/agent/*"]` in `pyproject.toml`. Then the 80% gate applies only to `banking_client` and `common` (D-11).
**Warning signs:** Coverage percentage seems unexpectedly high (100%) or low — check which files are in the report.

### Pitfall 3: CI Caching Masks Dependency Issues
**What goes wrong:** Cached uv dependencies hide a broken `pyproject.toml` — CI passes with stale cache but fails on a clean run.
**Why it happens:** `enable-cache: true` restores the previous uv cache, which may include packages that are no longer in the dependency list.
**How to avoid:** The `setup-uv` action uses `pyproject.toml` and lock files as cache keys by default, so the cache invalidates on dependency changes. Periodically verify with a clean run.
**Warning signs:** CI passes on repeat pushes but fails on the first push after a dependency change.

### Pitfall 4: Ruff Version Drift Between Pre-commit and CI
**What goes wrong:** The ruff version pinned in `astral-sh/ruff-pre-commit` (`rev: v0.15.19`) differs from the version installed via `uv` (`ruff>=0.11`). Different versions may have different rule behavior.
**Why it happens:** Pre-commit hooks pin their own ruff binary. The CI `uv run ruff check` uses whatever version `uv sync` installed.
**How to avoid:** Pin ruff to a specific version range in `pyproject.toml` (already `>=0.11`) and keep the pre-commit rev aligned. Accept minor version differences — the rule config in `pyproject.toml` is the same for both.
**Warning signs:** A file passes pre-commit locally but fails CI lint (or vice versa).

### Pitfall 5: mypy Path Resolution Differs Between Local and CI
**What goes wrong:** mypy works locally but fails in CI with `Cannot find module` errors, or vice versa.
**Why it happens:** `mypy_path = "$MYPY_CONFIG_FILE_DIR/src"` in `pyproject.toml` depends on mypy being invoked from the project root. If CI runs mypy from a different working directory, the path breaks.
**How to avoid:** Always run `uv run mypy` from the repo root in both CI and pre-commit. The `$MYPY_CONFIG_FILE_DIR` variable resolves relative to pyproject.toml location.
**Warning signs:** mypy import errors that don't reproduce locally.

## Code Examples

### GitHub Actions CI Workflow (ci.yml)
```yaml
# Source: docs.astral.sh/uv/guides/integration/github/ (adapted for project decisions)
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true
      - run: uv sync --all-extras --dev
      - run: uv run ruff check .
      - run: uv run ruff format --check .

  type-check:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true
          python-version: ${{ matrix.python-version }}
      - run: uv sync --all-extras --dev
      - run: uv run mypy

  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v8
        with:
          enable-cache: true
          python-version: ${{ matrix.python-version }}
      - run: uv sync --all-extras --dev
      - run: uv run pytest --cov --cov-report=term-missing
      - name: Enforce coverage threshold
        run: uv run coverage report --fail-under=80
```

### Pre-commit Configuration (.pre-commit-config.yaml)
```yaml
# Source: github.com/astral-sh/ruff-pre-commit + jaredkhan.com/blog/mypy-pre-commit
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.19
    hooks:
      - id: ruff-check
        args: [--fix]
      - id: ruff-format

  - repo: local
    hooks:
      - id: mypy
        name: mypy
        entry: uv run mypy
        language: system
        types: [python]
        require_serial: true
```

### Trivial Test (tests/test_common.py)
```python
# Tests target common/ stubs to prove pipeline works (D-12)
from common import OpenBankingError, __version__
from common.config import get_config
from common.errors import AuthenticationError, ConfigurationError
from common.logging import get_logger


def test_version_is_string() -> None:
    assert isinstance(__version__, str)


def test_get_config_returns_default() -> None:
    assert get_config("missing_key", "fallback") == "fallback"


def test_get_logger_returns_logger() -> None:
    logger = get_logger("test")
    assert logger.name == "test"


def test_error_hierarchy() -> None:
    assert issubclass(ConfigurationError, OpenBankingError)
    assert issubclass(AuthenticationError, OpenBankingError)
```

### Coverage Configuration (pyproject.toml additions)
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

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `pip install` + `venv` in CI | `astral-sh/setup-uv` with `uv sync` | 2024 | 10-50x faster installs, built-in caching |
| `black` + `isort` + `flake8` | `ruff` (all-in-one) | 2023-2024 | Single tool replaces three, 100x faster |
| `mirrors-mypy` pre-commit | `language: system` local hook | Ongoing | Avoids isolated env issues with typed dependencies |
| `--cov-fail-under` in pytest | Separate `coverage report --fail-under` | Best practice | Decouples test results from coverage enforcement |

**Deprecated/outdated:**
- `setup-python` action for uv projects: Use `setup-uv` instead — it handles Python installation and uv in one step
- `pre-commit/mirrors-mypy`: Still maintained but problematic for projects with typed dependencies

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `actions/checkout@v4` is current stable | Standard Stack | v7 exists but v4 is widely used and stable; low risk |
| A2 | `pre-commit/pre-commit-hooks` latest is v5.0.0 | Standard Stack | Version may differ; planner should verify during execution |
| A3 | `pre-commit` >= 4.0 is current | Standard Stack | Exact version TBD at install time via `uv add --dev pre-commit` |

## Open Questions

1. **Lint job: does it need the Python matrix?**
   - What we know: Ruff is a Rust binary — its lint results don't vary by Python version. Mypy and pytest do vary.
   - What's unclear: Whether to run the lint job once (no matrix) or per Python version.
   - Recommendation: Run lint once (no matrix) since ruff output is Python-version-independent. Run type-check and test in the matrix. This saves CI minutes and aligns with D-03 (separate jobs for clarity).

2. **`ruff format --check` in CI**
   - What we know: D-02 says CI runs `ruff check` (CI-02). The pre-commit hooks run both `ruff-check` and `ruff-format`.
   - What's unclear: Whether CI should also verify formatting with `ruff format --check`.
   - Recommendation: Include `ruff format --check` in the lint CI job. It mirrors the pre-commit `ruff-format` hook and catches formatting issues when someone skips pre-commit.

3. **`uv.lock` file**
   - What we know: `uv sync --locked` requires a lock file. `uv sync` without `--locked` generates one.
   - What's unclear: Whether a `uv.lock` exists yet from Phase 1.
   - Recommendation: Generate `uv.lock` if it doesn't exist. CI should use `uv sync --all-extras --dev` (without `--locked`) to avoid failing on lock drift, or commit the lock file and use `--locked`.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` | All CI and local commands | Yes | 0.9.20 | -- |
| Python | Runtime | Yes | 3.12.12 | -- |
| `gh` (GitHub CLI) | Not strictly required | Yes | 2.83.2 | -- |
| `pre-commit` | Hook installation | No (not yet installed) | -- | `uv add --dev pre-commit` then `uv run pre-commit install` |
| GitHub Actions runners | CI execution | Yes (GitHub-hosted) | ubuntu-latest | -- |

**Missing dependencies with no fallback:** None

**Missing dependencies with fallback:**
- `pre-commit`: Not installed locally yet. Install via `uv add --dev pre-commit` as part of phase execution.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | No | N/A (no auth in this phase) |
| V3 Session Management | No | N/A |
| V4 Access Control | No | N/A |
| V5 Input Validation | No | N/A (no user input processing) |
| V6 Cryptography | No | N/A |
| V14 Configuration | Yes | `.env.example` documents config vars without secrets; no real credentials |

### Known Threat Patterns for CI/CD

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Dependency confusion | Tampering | Pin action versions with SHA or major tag (e.g., `@v4`, `@v8`) |
| Secret leakage in CI logs | Information Disclosure | No secrets used in this phase; `.env.example` contains placeholders only |
| Malicious pre-commit hook repo | Tampering | Pin `rev` versions in `.pre-commit-config.yaml`; use official repos only |
| CI workflow injection via PR title/body | Tampering | No expression interpolation of untrusted input in workflow |

## Project Constraints (from CLAUDE.md)

- **Tech stack**: Python 3.12+, `uv`, `ruff`, `mypy --strict`, `pytest`, `hatchling` build backend
- **Compatibility**: CI must pass on both Python 3.12 and 3.13
- **Dependencies**: `mcp>=1.27,<2` locked now even though unused
- **Quality**: 80% coverage gate enforced in CI; pre-commit must mirror CI checks
- **Scope**: No business logic -- package skeletons only

## Sources

### Primary (HIGH confidence)
- [docs.astral.sh/uv/guides/integration/github/](https://docs.astral.sh/uv/guides/integration/github/) - GitHub Actions setup-uv patterns, caching, matrix strategy
- [github.com/astral-sh/ruff-pre-commit](https://github.com/astral-sh/ruff-pre-commit/blob/main/README.md) - Official ruff pre-commit hook IDs and configuration

### Secondary (MEDIUM confidence)
- [github.com/astral-sh/setup-uv](https://github.com/astral-sh/setup-uv) - setup-uv action latest version (v8.2.0)
- [pytest-cov.readthedocs.io](https://pytest-cov.readthedocs.io/en/latest/config.html) - Coverage configuration and fail-under
- [jaredkhan.com/blog/mypy-pre-commit](https://jaredkhan.com/blog/mypy-pre-commit) - mypy local hook pattern with language: system

### Tertiary (LOW confidence)
- WebSearch results for pre-commit-hooks version and checkout action version (marked [ASSUMED])

## Metadata

**Confidence breakdown:**
- Standard stack: MEDIUM - Versions verified via official docs and WebFetch; action SHA not pinned
- Architecture: HIGH - CI/hooks/docs is a well-understood domain with stable patterns
- Pitfalls: HIGH - Common issues documented across multiple sources, confirmed by project-specific constraints (mypy + mcp dependency, coverage exclusions)

**Research date:** 2026-06-25
**Valid until:** 2026-07-25 (stable domain, 30-day validity)
