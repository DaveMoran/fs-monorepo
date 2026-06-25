# Requirements: Open Banking MCP Capstone

**Defined:** 2026-06-24
**Core Value:** A reviewer can clone the repo and watch enterprise-grade tooling pass green before any business logic exists.

## v1 Requirements

Requirements for the scaffolding milestone. Each maps to roadmap phases.

### Package Structure

- [x] **PKG-01**: Project is a Python 3.12+ package managed with `uv`, using a `src/` layout
- [x] **PKG-02**: `src/banking_client/` exists as a package with `__init__.py` only (skeleton, no logic)
- [x] **PKG-03**: `src/mcp_server/` exists as a package with `__init__.py` only (intentionally empty)
- [x] **PKG-04**: `src/agent/` exists as a package with `__init__.py` only (intentionally empty)
- [x] **PKG-05**: `src/common/` exists as a package with `__init__.py` plus scaffolding for shared logging, config, and errors

### Tooling & Dependencies

- [x] **TOOL-01**: `pyproject.toml` declares the `hatchling` build backend wired for the src layout
- [x] **TOOL-02**: `mypy --strict` is configured in `pyproject.toml`
- [x] **TOOL-03**: `ruff` is configured for both linting and formatting
- [x] **TOOL-04**: `pytest` + `pytest-asyncio` + `pytest-cov` are configured (asyncio mode auto)
- [x] **TOOL-05**: `mcp>=1.27,<2` is pinned in dependencies even though it is unused

### Continuous Integration

- [x] **CI-01**: GitHub Actions workflow runs on a matrix of Python 3.12 and 3.13
- [x] **CI-02**: CI runs `ruff check` (lint)
- [x] **CI-03**: CI runs the `mypy --strict` type check
- [x] **CI-04**: CI runs `pytest` with coverage and fails when coverage drops below 80%

### Pre-commit Hooks

- [x] **HOOK-01**: `.pre-commit-config.yaml` runs `ruff` lint + format hooks
- [x] **HOOK-02**: `.pre-commit-config.yaml` runs the `mypy` type-check hook, mirroring CI

### Documentation & Licensing

- [x] **DOCS-01**: `README.md` includes a placeholder for the capstone spec excerpt
- [x] **DOCS-02**: `LICENSE` file contains the MIT license
- [x] **DOCS-03**: `CONTRIBUTING.md` provides contributor guidance (setup, checks, workflow)

### Configuration

- [x] **CONF-01**: `.env.example` documents the config vars (FDX base URL, auth stub key)

### Verification

- [x] **TEST-01**: One trivial passing test proves the pytest + coverage pipeline works end-to-end

## v2 Requirements

Deferred to future milestones. Tracked but not in this roadmap.

### Banking Client

- **BANK-01**: FDX API wrapper implementation in `src/banking_client/`

### MCP Server

- **MCP-01**: MCP server layer implementation in `src/mcp_server/` (user builds manually)

### Agent

- **AGENT-01**: Agent loop implementation in `src/agent/` (user builds manually)

## Out of Scope

Explicitly excluded from this milestone. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Any business logic | This milestone is bones only — package skeletons + tooling |
| Live FDX API calls / real credentials | Auth stub key only; no real integration yet |
| Filling `mcp_server/` or `agent/` | User implements these by hand in later prompts |
| Docker / deployment config | Not required to prove production tooling posture |
| Release/publish automation (PyPI) | Portfolio repo, not a distributed package |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PKG-01 | Phase 1 | Complete |
| PKG-02 | Phase 1 | Complete |
| PKG-03 | Phase 1 | Complete |
| PKG-04 | Phase 1 | Complete |
| PKG-05 | Phase 1 | Complete |
| TOOL-01 | Phase 1 | Complete |
| TOOL-02 | Phase 1 | Complete |
| TOOL-03 | Phase 1 | Complete |
| TOOL-04 | Phase 1 | Complete |
| TOOL-05 | Phase 1 | Complete |
| CI-01 | Phase 2 | Complete |
| CI-02 | Phase 2 | Complete |
| CI-03 | Phase 2 | Complete |
| CI-04 | Phase 2 | Complete |
| HOOK-01 | Phase 2 | Complete |
| HOOK-02 | Phase 2 | Complete |
| DOCS-01 | Phase 2 | Complete |
| DOCS-02 | Phase 2 | Complete |
| DOCS-03 | Phase 2 | Complete |
| CONF-01 | Phase 2 | Complete |
| TEST-01 | Phase 2 | Complete |

**Coverage:**

- v1 requirements: 19 total
- Mapped to phases: 19/19
- Unmapped: 0

---
*Requirements defined: 2026-06-24*
*Last updated: 2026-06-24 after roadmap creation*
