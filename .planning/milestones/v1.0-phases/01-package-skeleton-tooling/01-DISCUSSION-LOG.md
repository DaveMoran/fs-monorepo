# Phase 1: Package Skeleton & Tooling - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-24
**Phase:** 1-Package Skeleton & Tooling
**Areas discussed:** common/ scaffolding depth, ruff rule configuration, Package namespace style, __init__.py content

---

## common/ Scaffolding Depth

| Option | Description | Selected |
|--------|-------------|----------|
| Stub modules only | config.py, logging.py, errors.py each with a module docstring and stub class/function | ✓ |
| Minimal working implementations | Real get_logger() wrapper, Settings class, base exception hierarchy | |
| Empty __init__.py only | Treat common/ the same as mcp_server/ and agent/ | |

**User's choice:** Stub modules only
**Notes:** All three stubs selected (config.py, logging.py, errors.py)

| Option | Description | Selected |
|--------|-------------|----------|
| Full type hints + one-line docstrings | Every stub gets proper type annotations and a brief docstring | ✓ |
| Type hints only, no docstrings | Annotate parameters and returns but skip docstrings | |
| You decide | Let Claude pick | |

**User's choice:** Yes, full type hints + one-line docstrings

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, convenience re-exports | common/__init__.py imports and exposes main symbols via __all__ | ✓ |
| No, explicit submodule imports | Keep __init__.py minimal, consumers import from specific submodules | |

**User's choice:** Yes, convenience re-exports via __all__

---

## Ruff Rule Configuration

| Option | Description | Selected |
|--------|-------------|----------|
| Expanded enterprise set | E, F, I, B, UP, SIM, D, plus a few more | ✓ |
| Ruff defaults only | E, F only | |
| Kitchen sink | Nearly all rule sets | |

**User's choice:** Expanded enterprise set

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, Google-style docstrings | D rules with Google convention | ✓ |
| Yes, NumPy-style docstrings | D rules with NumPy convention | |
| No docstring enforcement | Skip D rules | |

**User's choice:** Yes, Google-style docstrings

| Option | Description | Selected |
|--------|-------------|----------|
| Python 3.12 | Matches minimum supported version | ✓ |
| Python 3.13 | Target latest, may cause compatibility issues | |

**User's choice:** Python 3.12

| Option | Description | Selected |
|--------|-------------|----------|
| 88 | Black/ruff default | |
| 120 | More permissive, common in enterprise codebases | ✓ |
| 79 | PEP 8 original | |

**User's choice:** 120

---

## Package Namespace Style

| Option | Description | Selected |
|--------|-------------|----------|
| Flat packages | src/banking_client/, src/mcp_server/, etc. Top-level imports | ✓ |
| Shared namespace package | src/open_banking/banking_client/, etc. Grouped under umbrella | |
| Underscore-prefixed flat | src/ob_banking_client/, etc. Flat with project prefix | |

**User's choice:** Flat packages

| Option | Description | Selected |
|--------|-------------|----------|
| Single project, internal packages | One pyproject.toml, hatchling discovers all packages | ✓ |
| Separate installable packages | Each package gets own pyproject.toml or hatch workspaces | |

**User's choice:** Single project, internal packages

---

## __init__.py Content

| Option | Description | Selected |
|--------|-------------|----------|
| Module docstring + __version__ | One-line docstring and __version__ string | ✓ |
| Module docstring only | Just a docstring, no __version__ | |
| Empty file | Truly empty, may need ruff noqa | |

**User's choice:** Module docstring + __version__

| Option | Description | Selected |
|--------|-------------|----------|
| pyproject.toml via hatchling | Version in pyproject.toml, read dynamically via importlib.metadata | ✓ |
| Hardcoded in __init__.py | __version__ = '0.1.0' in each package | |
| You decide | Let Claude pick | |

**User's choice:** pyproject.toml via hatchling (importlib.metadata.version())

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, include py.typed | PEP 561 marker in each package root | ✓ |
| No, skip py.typed | Not strictly needed for internal project | |

**User's choice:** Yes, include py.typed

---

## Claude's Discretion

No areas deferred to Claude's discretion.

## Deferred Ideas

None — discussion stayed within phase scope.
