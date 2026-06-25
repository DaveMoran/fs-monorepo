# Phase 2: CI, Hooks, Docs & Verification - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-25
**Phase:** 02-CI, Hooks, Docs & Verification
**Areas discussed:** CI trigger strategy, Pre-commit scope, Contributing guide depth, Coverage accounting

---

## CI Trigger Strategy

| Option | Description | Selected |
|--------|-------------|----------|
| Push + PR to main only | CI fires on pushes to main and PRs targeting main. Clean — reviewers see green on main, feature branches don't trigger CI until a PR is opened. | ✓ |
| Push to all branches + PRs | CI fires on every push to any branch and on all PRs. Maximum safety but noisier. | |
| PRs only (no push) | CI fires only when a PR is opened/updated. Lightweight. | |

**User's choice:** Push + PR to main only

| Option | Description | Selected |
|--------|-------------|----------|
| "CI" (minimal) | Short, clean badge. Most common convention for single-workflow repos. | ✓ |
| "Tests & Lint" (descriptive) | Tells reviewers at a glance what runs. | |
| You decide | Claude picks what fits best. | |

**User's choice:** "CI" (minimal)

| Option | Description | Selected |
|--------|-------------|----------|
| Single job, sequential steps | Simpler YAML, one runner per matrix entry. Faster for small repos. | |
| Separate jobs (parallel) | Lint, type-check, and test run as independent jobs. Gives clearer per-check status badges. | ✓ |
| You decide | Claude picks approach for skeleton repo. | |

**User's choice:** Separate jobs (parallel)

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, cache uv dependencies | Caches the uv virtualenv between runs. Standard practice. | ✓ |
| No caching | Simpler workflow, installs fresh every time. | |
| You decide | Claude decides based on portfolio standards. | |

**User's choice:** Yes, cache uv dependencies

---

## Pre-commit Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Ruff only (fast) | Just ruff lint + format. Sub-second. Mypy and tests run in CI only. | |
| Ruff + mypy (thorough) | Lint, format, and type-check locally. Matches CI more closely. | ✓ |
| Ruff + mypy + tests (full mirror) | Mirrors CI completely. Slower but zero surprises. | |

**User's choice:** Initially chose ruff-only, but kept mypy to satisfy HOOK-02 requirement.

| Option | Description | Selected |
|--------|-------------|----------|
| Local hook (runs in project venv) | Uses project's own virtualenv via language: system. Always matches pyproject.toml. | ✓ |
| Mirror repo hook | Uses pre-commit's mirrors-mypy repo. Isolated but needs additional_dependencies. | |
| You decide | Claude picks cleanest approach with uv. | |

**User's choice:** Local hook (runs in project venv)

| Option | Description | Selected |
|--------|-------------|----------|
| Official ruff-pre-commit repo | Standard approach. Pre-commit manages the ruff version. Widely adopted. | ✓ |
| Local hooks (like mypy) | Uses project-installed ruff from venv. Guarantees exact same version. | |
| You decide | Claude picks for consistency. | |

**User's choice:** Official ruff-pre-commit repo

---

## Contributing Guide Depth

| Option | Description | Selected |
|--------|-------------|----------|
| Setup-focused (minimal) | Prerequisites, install steps, how to run checks. 1 page. | |
| Full workflow guide | Setup + PR workflow + commit conventions + code style expectations. 2-3 pages. | ✓ |
| You decide | Claude picks depth for portfolio repo. | |

**User's choice:** Full workflow guide

| Option | Description | Selected |
|--------|-------------|----------|
| Conventional Commits | feat:, fix:, docs:, chore: prefixes. Well-known standard. | ✓ |
| No enforced convention | Suggest clear messages but don't mandate a format. | |
| You decide | Claude picks for enterprise posture. | |

**User's choice:** Conventional Commits

| Option | Description | Selected |
|--------|-------------|----------|
| Structured with badges + sections | CI badge, project description, quick start, development setup, architecture overview. | ✓ |
| Minimal with spec placeholder | Short description + spec excerpt placeholder. | |
| You decide | Claude picks for skeleton. | |

**User's choice:** Structured with badges + sections

---

## Coverage Accounting

| Option | Description | Selected |
|--------|-------------|----------|
| Include all packages | Measure coverage across all src/ packages. Honest accounting. | |
| Exclude empty packages | Only measure banking_client and common (real code). 80% of real code is meaningful. | ✓ |
| You decide | Claude picks meaningful approach. | |

**User's choice:** Exclude empty packages (mcp_server, agent)

| Option | Description | Selected |
|--------|-------------|----------|
| Import + version check | Test importing packages and __version__ is valid semver. | |
| Common module stubs | Test common/ scaffolding (config, logging, errors stubs). More coverage. | ✓ |
| Both (import + common stubs) | Version check AND common stub tests. | |

**User's choice:** Common module stubs

| Option | Description | Selected |
|--------|-------------|----------|
| pytest-cov --cov-fail-under=80 | Single command. Test run fails if coverage drops. Simple, standard. | |
| Separate coverage check step | Run pytest --cov first, then separate step parses report. More flexible. | ✓ |
| You decide | Claude picks cleanest approach. | |

**User's choice:** Separate coverage check step

---

## Claude's Discretion

No areas deferred to Claude's discretion.

## Deferred Ideas

None — discussion stayed within phase scope.
