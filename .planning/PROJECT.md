# Open Banking MCP Capstone

## What This Is

A production-grade Python repository for an Open Banking MCP (Model Context Protocol)
capstone. This milestone establishes the repository *bones* — a four-package src-layout
skeleton, strict tooling, CI/CD, pre-commit, and contributor docs — that later prompts will
fill with an FDX API client, an MCP server, and an agent loop. It is a portfolio piece built
to demonstrate enterprise-grade product-engineering posture from the first commit.

## Core Value

Production posture from commit #1: a reviewer can clone the repo and watch enterprise-grade
tooling — strict typing, lint/format, a Python 3.12/3.13 CI matrix, an 80% coverage gate, and
pre-commit hooks — all pass green *before any business logic exists*.

## Requirements

### Validated

- ✓ Python 3.12+ project managed with `uv`, using a `src/` layout — Phase 1
- ✓ Four-package skeleton (`banking_client`, `mcp_server`, `agent`, `common`) with `__init__.py` only — Phase 1
- ✓ `pyproject.toml`: strict mypy, ruff (lint + format), pytest + pytest-asyncio + pytest-cov — Phase 1
- ✓ `mcp>=1.27,<2` pinned in dependencies despite being unused (locks the major version) — Phase 1
- ✓ GitHub Actions CI: matrix on Python 3.12 and 3.13, running ruff check, mypy, and pytest with an 80% coverage gate — Phase 2
- ✓ Pre-commit hooks mirroring CI (ruff, mypy) — Phase 2
- ✓ README.md with a placeholder for the capstone spec excerpt — Phase 2
- ✓ LICENSE (MIT) and CONTRIBUTING.md — Phase 2
- ✓ `.env.example` showing config vars (FDX base URL, auth stub key) — Phase 2
- ✓ One trivial passing test proving CI works end-to-end — Phase 2

### Active

(None — all milestone requirements validated)

### Out of Scope

- FDX banking client implementation — built in later prompts, scaffold only now
- MCP server implementation — user builds this manually later; package left empty
- Agent loop implementation — user builds this manually later; package left empty
- Any business logic — this milestone is bones only

## Current State

Shipped v1.0 MVP on 2026-06-25 with 122 LOC Python across 4 packages.
Tech stack: Python 3.12+, uv, hatchling, mypy --strict, ruff, pytest, GitHub Actions CI.
All 19 requirements validated. 83% test coverage. CI green on Python 3.12 and 3.13.

## Context

- Portfolio project targeting an enterprise product-engineering role; production posture
  matters more than speed.
- `src/mcp_server/` and `src/agent/` are intentionally left empty (only `__init__.py`) — the
  user implements those by hand in later work.
- `src/common/` is the one shared package that gets minimal real content (logging, config,
  errors scaffolding) to support future packages.
- The trivial passing test exists purely to prove the CI pipeline is wired correctly.

## Constraints

- **Tech stack**: Python 3.12+, `uv`, `ruff`, `mypy --strict`, `pytest`, `hatchling` build backend
- **Compatibility**: CI must pass on both Python 3.12 and 3.13
- **Dependencies**: `mcp>=1.27,<2` locked now even though unused
- **Quality**: 80% coverage gate enforced in CI; pre-commit must mirror CI checks
- **Scope**: No business logic — package skeletons only

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Type checker: `mypy --strict` | Enterprise-standard, pure-Python, no extra toolchain to maintain | ✓ Phase 1 |
| Build backend: `hatchling` | Widely adopted, near-zero config for src layout, strong enterprise track record | ✓ Phase 1 |
| `ruff` for lint **and** format | Single fast tool replacing black/isort/flake8 | ✓ Phase 1 |
| Pin `mcp>=1.27,<2` while unused | Lock the MCP major version ahead of the MCP server work | ✓ Phase 1 |
| Empty `mcp_server/` + `agent/` | User implements these by hand in later prompts | ✓ Phase 1 |
| Coverage omit for empty packages | Exclude mcp_server/agent from coverage to measure only real code | ✓ Phase 2 |
| Coverage gate as separate CI step | `coverage report --fail-under=80`, not a pytest flag | ✓ Phase 2 |
| mypy hook via `language: system` | Uses project venv via `uv run mypy` to resolve deps | ✓ Phase 2 |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd-complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-06-25 after v1.0 milestone*
