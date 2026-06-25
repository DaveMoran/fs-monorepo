# Phase 2: CI, Hooks, Docs & Verification - Context

**Gathered:** 2026-06-25
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase layers CI/CD infrastructure, developer workflow automation, documentation, and end-to-end verification onto the Phase 1 skeleton. A reviewer can push to GitHub and watch CI pass green on Python 3.12 and 3.13, with pre-commit hooks mirroring CI checks, contributor docs in place, and a trivial test proving the pipeline works.

</domain>

<decisions>
## Implementation Decisions

### CI Workflow
- **D-01:** CI triggers on push to `main` and PRs targeting `main` only — feature branches don't fire CI until a PR is opened.
- **D-02:** Workflow named `CI` (minimal naming convention).
- **D-03:** Lint, type-check, and test run as separate parallel jobs (not sequential steps in one job) — gives clearer per-check status in GitHub.
- **D-04:** Cache `uv` dependencies between CI runs to speed up repeat pushes.

### Pre-commit Hooks
- **D-05:** Pre-commit runs ruff (lint + format) and mypy. Tests are CI-only, not in pre-commit.
- **D-06:** Ruff hooks use the official `astral-sh/ruff-pre-commit` repo.
- **D-07:** Mypy runs as a local hook (`language: system`) using the project virtualenv — ensures access to installed dependencies like `mcp` and matches `pyproject.toml` config exactly.

### Documentation
- **D-08:** CONTRIBUTING.md is a full workflow guide: setup instructions, PR workflow, commit conventions, and code style expectations (2-3 pages). Enterprise-grade contributor onboarding.
- **D-09:** Conventional Commits enforced: `feat:`, `fix:`, `docs:`, `chore:` prefixes.
- **D-10:** README.md structured with CI badge, project description, quick start, development setup, and architecture overview. Professional portfolio look.

### Coverage Strategy
- **D-11:** Coverage excludes intentionally empty packages (`mcp_server`, `agent`) — only measure `banking_client` and `common` (packages with actual code). 80% gate applies to real code.
- **D-12:** Trivial test targets `common/` module stubs (config, logging, errors) — proves stubs are importable and typed correctly, covering real code.
- **D-13:** Coverage enforcement uses a separate CI step (not `--cov-fail-under`) — enables report upload and badge generation.

### Claude's Discretion
No areas deferred to Claude's discretion — all decisions were made by the user.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Definition
- `.planning/PROJECT.md` — Core value, constraints, key decisions, and context for the entire capstone
- `.planning/REQUIREMENTS.md` — All v1 requirements (CI-01–04, HOOK-01–02, DOCS-01–03, CONF-01, TEST-01 for this phase) with traceability matrix
- `.planning/ROADMAP.md` — Phase goals, success criteria, and dependencies

### Prior Phase Context
- `.planning/phases/01-package-skeleton-tooling/01-CONTEXT.md` — Phase 1 decisions (ruff rules, package namespace, __init__.py content, mypy config) that CI/hooks must align with

### Configuration (source of truth)
- `pyproject.toml` — All tool configuration (mypy, ruff, pytest) lives here; CI and hooks must read from it, not duplicate config

No external specs — requirements fully captured in project planning documents and decisions above.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `pyproject.toml` — Already configures mypy (strict, py312, src path), ruff (E/F/I/B/UP/SIM/D, Google docstrings, 120-char lines), and pytest (testpaths=tests, asyncio_mode=auto). CI and hooks align with this, not duplicate it.

### Established Patterns
- Flat packages under `src/` with `mypy_path = "$MYPY_CONFIG_FILE_DIR/src"` — mypy CI step and local hook must use the same path resolution
- `importlib.metadata.version()` in `__init__.py` — test can verify this works without importing every package
- `py.typed` markers in every package root — mypy runs in strict mode expecting these

### Integration Points
- `src/common/{config,logging,errors}.py` — primary test targets for the trivial test; these have real type annotations and stubs to cover
- `src/banking_client/__init__.py` — has typed content worth including in coverage
- No `.github/workflows/`, `.pre-commit-config.yaml`, `LICENSE`, `CONTRIBUTING.md`, or `.env.example` exist yet — all are net-new files

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches within the decisions captured above.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 2-CI, Hooks, Docs & Verification*
*Context gathered: 2026-06-25*
