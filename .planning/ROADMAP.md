# Roadmap: Open Banking MCP Capstone

## Overview

This milestone delivers a cloneable, CI-green Python repository skeleton with strict tooling, four empty packages, and contributor documentation -- proving enterprise-grade production posture before any business logic exists. Two phases: first lay the package skeleton and wire up all local tooling, then layer on CI, pre-commit hooks, docs, and the trivial test that proves everything works end-to-end.

## Phases

**Phase Numbering:**

- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Package Skeleton & Tooling** - src-layout packages, pyproject.toml with hatchling, mypy/ruff/pytest config, and mcp pin (completed 2026-06-25)
- [x] **Phase 2: CI, Hooks, Docs & Verification** - GitHub Actions matrix, pre-commit hooks, contributor docs, .env.example, and the trivial passing test (completed 2026-06-25)

## Phase Details

### Phase 1: Package Skeleton & Tooling

**Goal**: A developer can clone the repo, run `uv sync`, and have all four packages resolve with mypy --strict and ruff reporting zero errors on the skeleton code
**Mode:** mvp
**Depends on**: Nothing (first phase)
**Requirements**: PKG-01, PKG-02, PKG-03, PKG-04, PKG-05, TOOL-01, TOOL-02, TOOL-03, TOOL-04, TOOL-05
**Success Criteria** (what must be TRUE):

  1. `uv sync` completes without errors and installs the project in a src-layout virtualenv
  2. Four packages exist under `src/` (banking_client, mcp_server, agent, common) each with `__init__.py`; mcp_server and agent contain only `__init__.py`
  3. `mypy --strict src/` reports zero errors on the skeleton
  4. `ruff check src/` and `ruff format --check src/` report zero violations

**Plans**: 1/1 plans complete

- [x] 01-01-PLAN.md — Walking Skeleton: pyproject.toml (hatchling, strict mypy/ruff/pytest, mcp pin) + four src-layout packages with typed __init__, py.typed markers, common stubs; uv sync + mypy + ruff pass green

### Phase 2: CI, Hooks, Docs & Verification

**Goal**: A reviewer can push to GitHub and watch CI pass green on Python 3.12 and 3.13, with pre-commit hooks mirroring CI checks and contributor docs in place
**Mode:** mvp
**Depends on**: Phase 1
**Requirements**: CI-01, CI-02, CI-03, CI-04, HOOK-01, HOOK-02, DOCS-01, DOCS-02, DOCS-03, CONF-01, TEST-01
**Success Criteria** (what must be TRUE):

  1. GitHub Actions CI passes green on both Python 3.12 and 3.13, running ruff check, mypy --strict, and pytest with an 80% coverage gate
  2. `pre-commit run --all-files` passes, running ruff lint/format and mypy hooks that mirror the CI checks
  3. One trivial test exists and passes, producing coverage at or above 80%
  4. README.md, LICENSE (MIT), CONTRIBUTING.md, and .env.example all exist with appropriate content

**Plans**: 2/2 plans complete

- [x] 02-01-PLAN.md — Verification slice: trivial test on common/, coverage config (omit empty packages), and the CI workflow (3.12/3.13 matrix, ruff/mypy/pytest, 80% gate)
- [x] 02-02-PLAN.md — Pre-commit hooks (ruff + local mypy), MIT LICENSE, structured README with CI badge, CONTRIBUTING guide, and .env.example

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Package Skeleton & Tooling | 1/1 | Complete    | 2026-06-25 |
| 2. CI, Hooks, Docs & Verification | 2/2 | Complete   | 2026-06-25 |
