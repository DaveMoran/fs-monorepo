# Phase 1: Package Skeleton & Tooling - Context

**Gathered:** 2026-06-24
**Status:** Ready for planning

<domain>
## Phase Boundary

This phase delivers the repository's foundational structure: a Python 3.12+ project with four flat packages under `src/`, a fully-configured `pyproject.toml` (hatchling build backend), and strict tooling (mypy --strict, ruff with expanded enterprise rules, pytest). A developer can clone the repo, run `uv sync`, and have all four packages resolve with zero errors from mypy and ruff on the skeleton code.

</domain>

<decisions>
## Implementation Decisions

### common/ Scaffolding Depth
- **D-01:** common/ contains stub modules only — no working implementations. Three stub files: `config.py`, `logging.py`, `errors.py`.
- **D-02:** All stubs include full type annotations and one-line Google-style docstrings to exercise mypy --strict and ruff's D rules on real signatures.
- **D-03:** `common/__init__.py` provides convenience re-exports via `__all__` so downstream packages can import directly from `common` (e.g., `from common import OpenBankingError`).

### Ruff Rule Configuration
- **D-04:** Expanded enterprise rule set: E (pycodestyle), F (pyflakes), I (isort), B (bugbear), UP (pyupgrade), SIM (simplify), D (pydocstyle/Google convention), plus additional quality rules.
- **D-05:** Google-style docstrings enforced via ruff's D rules with `convention = "google"`.
- **D-06:** Target Python version is 3.12 for pyupgrade rules (matches CI matrix minimum).
- **D-07:** Line length limit is 120 characters.

### Package Namespace Style
- **D-08:** Flat packages under `src/` — `banking_client`, `mcp_server`, `agent`, `common`. Top-level imports (e.g., `import banking_client`), no shared namespace nesting.
- **D-09:** Single project with one `pyproject.toml`; hatchling discovers all packages under `src/`. Not separate installable packages.

### __init__.py Content
- **D-10:** All skeleton packages' `__init__.py` files contain a module docstring describing the package purpose and a `__version__` string.
- **D-11:** Version source of truth is `pyproject.toml` `[project]` version field. `__init__.py` reads it dynamically via `importlib.metadata.version()`.
- **D-12:** PEP 561 `py.typed` marker files included in every package root.

### Claude's Discretion
No areas deferred to Claude's discretion — all decisions were made by the user.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Project Definition
- `.planning/PROJECT.md` — Core value, constraints, key decisions, and context for the entire capstone
- `.planning/REQUIREMENTS.md` — All v1 requirements (PKG-01–05, TOOL-01–05 for this phase) with traceability matrix
- `.planning/ROADMAP.md` — Phase goals, success criteria, and dependencies

No external specs — requirements fully captured in project planning documents and decisions above.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- None — greenfield project with only a README.md

### Established Patterns
- None — this phase establishes the foundational patterns

### Integration Points
- None — first phase; subsequent phases build on the skeleton created here

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

*Phase: 1-Package Skeleton & Tooling*
*Context gathered: 2026-06-24*
