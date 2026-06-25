<!-- GSD:project-start source:PROJECT.md -->

## Project

**Open Banking MCP Capstone**

A production-grade Python repository for an Open Banking MCP (Model Context Protocol)
capstone. This milestone establishes the repository *bones* — a four-package src-layout
skeleton, strict tooling, CI/CD, pre-commit, and contributor docs — that later prompts will
fill with an FDX API client, an MCP server, and an agent loop. It is a portfolio piece built
to demonstrate enterprise-grade product-engineering posture from the first commit.

**Core Value:** Production posture from commit #1: a reviewer can clone the repo and watch enterprise-grade
tooling — strict typing, lint/format, a Python 3.12/3.13 CI matrix, an 80% coverage gate, and
pre-commit hooks — all pass green *before any business logic exists*.

### Constraints

- **Tech stack**: Python 3.12+, `uv`, `ruff`, `mypy --strict`, `pytest`, `hatchling` build backend
- **Compatibility**: CI must pass on both Python 3.12 and 3.13
- **Dependencies**: `mcp>=1.27,<2` locked now even though unused
- **Quality**: 80% coverage gate enforced in CI; pre-commit must mirror CI checks
- **Scope**: No business logic — package skeletons only

<!-- GSD:project-end -->

<!-- GSD:stack-start source:STACK.md -->

## Technology Stack

Technology stack not yet documented. Will populate after codebase mapping or first phase.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->

## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->

## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->

## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->

## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:

- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->

## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
