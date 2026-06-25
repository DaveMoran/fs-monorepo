# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — MVP

**Shipped:** 2026-06-25
**Phases:** 2 | **Plans:** 3 | **Tasks:** 9

### What Was Built
- Four-package src-layout skeleton (banking_client, mcp_server, agent, common) with strict typing
- GitHub Actions CI matrix (Python 3.12/3.13) with ruff, mypy --strict, pytest, and 80% coverage gate
- Pre-commit hooks mirroring CI, MIT LICENSE, portfolio-grade README, CONTRIBUTING guide, .env.example

### What Worked
- Two-phase split (skeleton first, then CI/docs) kept each phase focused and testable
- Pattern-following approach: researching existing codebase patterns before planning kept plans grounded
- Coverage omit strategy for empty packages let the gate work correctly from day one
- Verification via UAT caught the setup-uv v8 pin issue before it became a blocker

### What Was Inefficient
- Initial CI workflow referenced setup-uv v8 which doesn't exist — required a fix commit
- Phase 2 could have been a single plan instead of two, given the small scope

### Patterns Established
- `language: system` for mypy pre-commit hook (uses project venv via `uv run`)
- Coverage gate as separate CI step (`coverage report --fail-under=80`), not a pytest flag
- Conventional Commits format with phase prefix: `feat(01):`, `docs(02):`

### Key Lessons
1. Always pin GitHub Actions to known-good versions — verify the version exists before referencing it
2. Empty package skeletons need explicit coverage omit to avoid skewing the coverage gate
3. Enterprise posture can be proven with ~120 LOC if the tooling is correctly wired

### Cost Observations
- Model mix: primarily sonnet
- Sessions: ~3 sessions over 2 days
- Notable: entire milestone completed in under 24 hours of wall time

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Sessions | Phases | Key Change |
|-----------|----------|--------|------------|
| v1.0 | ~3 | 2 | Initial project setup with GSD workflow |

### Cumulative Quality

| Milestone | Tests | Coverage | Phases |
|-----------|-------|----------|--------|
| v1.0 | 5 | 83% | 2 |

### Top Lessons (Verified Across Milestones)

1. Pin CI tool versions to known-good releases — never assume latest major exists
2. Enterprise posture from commit #1 pays off in reviewer confidence
