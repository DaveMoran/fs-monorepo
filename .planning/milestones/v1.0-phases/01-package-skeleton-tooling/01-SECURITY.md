---
phase: 01
slug: package-skeleton-tooling
status: verified
threats_open: 0
asvs_level: 1
created: 2026-06-25
---

# Phase 01 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| PyPI registry → local build env | Third-party packages (hatchling, mypy, ruff, pytest*, mcp) downloaded and installed during `uv sync` | Package wheels / sdists |
| pyproject.toml → installed environment | Declared dependency specifiers resolved into concrete installed versions | Dependency version constraints |

---

## Threat Register

| Threat ID | Category | Component | Severity | Disposition | Mitigation | Status |
|-----------|----------|-----------|----------|-------------|------------|--------|
| T-01-SC | Tampering | `uv sync` package installs | medium | mitigate | Pin `mcp>=1.27,<2` in pyproject.toml; commit `uv.lock` for reproducible, auditable resolved versions | closed |
| T-01-02 | Tampering | Build backend (hatchling) supply chain | low | accept | hatchling is PyPA-maintained (github.com/pypa/hatch); pinned transitively via uv.lock | closed |
| T-01-03 | Elevation | Malicious package postinstall scripts during `uv sync` | low | accept | All dependencies are long-established canonical packages from known orgs; uv resolves from PyPI with lock pinning | closed |

*Status: open · closed · open — below high threshold (non-blocking)*
*Severity: critical > high > medium > low — only open threats at or above high count toward threats_open*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-01 | T-01-02 | hatchling is PyPA-maintained; standard ecosystem backend with no in-house build code | gsd-secure-phase | 2026-06-25 |
| AR-02 | T-01-03 | All 7 dependencies are canonical 4-15yr packages from PyPA/Astral/pytest-dev/Anthropic; uv resolves with lock pinning | gsd-secure-phase | 2026-06-25 |

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-06-25 | 3 | 3 | 0 | gsd-secure-phase |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-06-25
