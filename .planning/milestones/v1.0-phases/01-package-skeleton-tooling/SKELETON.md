# Walking Skeleton — Open Banking MCP Capstone

**Phase:** 1
**Generated:** 2026-06-24

## Capability Proven End-to-End

> One sentence: the smallest user-visible capability that exercises the full stack.

A developer can clone the repo, run `uv sync`, and watch `mypy --strict src/` and `ruff check src/` report zero errors on a four-package src-layout skeleton — proving the enterprise tooling chain (build backend → type checker → linter/formatter → test config → dependency pinning) works green before any business logic exists.

> Note: this is a tooling/infrastructure capstone, not a web app. The "full stack" being proven is the local quality toolchain, not a UI→API→DB request path. There is no HTTP server, database, or browser UI in this milestone by design (see REQUIREMENTS.md "Out of Scope").

## Architectural Decisions

| Decision | Choice | Rationale |
|---|---|---|
| Language / runtime | Python 3.12+ (CI also 3.13 in Phase 2) | Locked in CLAUDE.md constraints; 3.12 is pyupgrade target (D-06) |
| Package manager | `uv` 0.9+ | Locked constraint; fast resolver, manages venv + lock file |
| Build backend | `hatchling` 1.30+ | PyPA-maintained, near-zero config for src layout (D-09); single project, not separate distributions |
| Project layout | `src/` layout, four flat packages | `banking_client`, `mcp_server`, `agent`, `common` — top-level imports, no namespace nesting (D-08) |
| Distribution name | `open-banking-mcp` (single distribution) | All four packages share one version via `importlib.metadata.version("open-banking-mcp")` (D-11, Pitfall 1) |
| Type checking | `mypy --strict` | Enterprise standard; `mypy_path` + explicit packages list resolves src-layout imports (D, Pitfall 2) |
| Lint + format | `ruff` (single tool) | Replaces black/isort/flake8; rules E,F,I,B,UP,SIM,D; Google docstring convention; line-length 120 (D-04..D-07) |
| Test framework | `pytest` + `pytest-asyncio` (auto) + `pytest-cov` | Configured now, exercised in Phase 2 (trivial test + 80% coverage gate) (TOOL-04) |
| Versioning | `importlib.metadata.version()` from pyproject `[project] version` | Single source of truth; no hard-coded version drift (D-11) |
| Type marker | PEP 561 `py.typed` in every package | Marks packages as typed for downstream consumers (D-12) |
| `common/` depth | Stub modules only (config, logging, errors) | Full annotations + Google docstrings, no implementations (D-01, D-02); `__all__` re-exports (D-03) |

## Stack Touched in Phase 1

- [x] Project scaffold — `pyproject.toml` (hatchling build, deps, mypy/ruff/pytest config)
- [x] Package structure — four real importable packages under `src/`
- [x] Dependency resolution — `uv sync` writes `uv.lock`, installs project + dev tools
- [x] Type checking — `mypy --strict src/` green on annotated skeleton
- [x] Lint + format — `ruff check src/` and `ruff format --check src/` green
- [x] Local full-stack run command — `uv sync && uv run mypy --strict src/ && uv run ruff check src/` (the documented end-to-end gate; no HTTP/DB/UI by design)

> Not applicable to this milestone (tooling capstone): live HTTP routing, database read/write, browser UI, deployment to a hosted dev environment. These belong to v2 business-logic milestones.

## Out of Scope (Deferred to Later Slices)

> Anything that is *not* in the skeleton. Be explicit — this list prevents future phases from re-litigating Phase 1's minimalism.

- GitHub Actions CI matrix (3.12 / 3.13), `ruff check` + `mypy` + `pytest` coverage gate in CI → **Phase 2**
- Pre-commit hooks mirroring CI (`.pre-commit-config.yaml`) → **Phase 2**
- Contributor docs: `README.md` spec excerpt, `LICENSE` (MIT), `CONTRIBUTING.md` → **Phase 2**
- `.env.example` (FDX base URL, auth stub key) → **Phase 2**
- One trivial passing test proving pytest + coverage pipeline (TEST-01) → **Phase 2**
- Any business logic: FDX API client (`banking_client`), MCP server (`mcp_server`), agent loop (`agent`) → **v2 milestone**
- Live FDX API calls, real credentials, Docker/deployment, PyPI publishing → **out of scope entirely** (REQUIREMENTS.md)

## Subsequent Slice Plan

Each later phase adds one vertical slice on top of this skeleton without altering its architectural decisions:

- **Phase 2:** CI, Hooks, Docs & Verification — push to GitHub and watch CI pass green on 3.12 + 3.13 with pre-commit mirroring CI, contributor docs in place, and one trivial test producing ≥80% coverage.
- **v2 milestone:** Fill `banking_client` (FDX API wrapper), `mcp_server` (MCP server layer), and `agent` (agent loop) with real business logic — each reusing `common/` stubs (config, logging, errors) hardened into implementations.
