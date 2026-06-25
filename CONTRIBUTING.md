# Contributing to Open Banking MCP Capstone

Thank you for your interest in contributing. This guide covers environment setup,
development workflow, commit conventions, and code style expectations.

## Getting Started

### Prerequisites

- Python 3.12 or later
- [uv](https://docs.astral.sh/uv/) package manager

### Setup

Clone the repository and install all dependencies (including dev tools):

```bash
git clone https://github.com/DaveMoran/fs-monorepo.git
cd fs-monorepo
uv sync --all-extras --dev
```

Install the pre-commit hooks so lint and type checks run automatically on each commit:

```bash
uv run pre-commit install
```

Verify your setup by running the full quality check suite:

```bash
uv run pre-commit run --all-files
uv run pytest --cov
```

## Development Workflow

1. **Create a branch** from `main` for your work:

   ```bash
   git checkout -b feat/your-feature-name
   ```

2. **Make your changes.** Write code, add tests, update documentation as needed.

3. **Run checks locally** before committing:

   ```bash
   uv run pre-commit run --all-files
   uv run pytest --cov
   ```

   Pre-commit runs ruff (lint + format) and mypy (strict type checking) automatically.
   Tests run separately -- they are not part of pre-commit to keep commits fast.

4. **Commit using Conventional Commits** (see below).

5. **Open a Pull Request** targeting `main`. CI will run lint, type-check, and tests
   on Python 3.12 and 3.13. All checks must pass before merge.

## Commit Conventions

This project follows [Conventional Commits](https://www.conventionalcommits.org/).
Every commit message must use one of the following prefixes:

| Prefix   | When to use                                      | Example                                      |
|----------|--------------------------------------------------|----------------------------------------------|
| `feat:`  | New feature or capability                        | `feat: add account balance endpoint`         |
| `fix:`   | Bug fix or error correction                      | `fix: handle null account ID in response`    |
| `docs:`  | Documentation-only changes                       | `docs: update README quick start section`    |
| `chore:` | Tooling, config, dependencies, CI                | `chore: pin ruff pre-commit hook to v0.15`   |

Additional prefixes (`refactor:`, `test:`, `perf:`, `style:`) are accepted but the
four above cover most contributions.

### Format

```
<prefix>: <short imperative description>

<optional body explaining why, not what>
```

Keep the subject line under 72 characters. Use the body for context that the diff
alone does not convey.

## Code Style

All style enforcement is automated -- you do not need to memorize rules.

### Linting and Formatting

[Ruff](https://docs.astral.sh/ruff/) handles both linting and formatting. The full
rule configuration lives in `pyproject.toml` under `[tool.ruff]`:

- **Rules:** E, F, I, B, UP, SIM, D (Google-style docstrings)
- **Line length:** 120 characters
- **Target:** Python 3.12

Run manually:

```bash
uv run ruff check .       # lint
uv run ruff format .      # format in place
```

### Type Checking

[mypy](https://mypy-lang.org/) runs in strict mode. All function signatures must
have type annotations. The configuration in `pyproject.toml` under `[tool.mypy]`
applies to all four packages.

Run manually:

```bash
uv run mypy
```

### Testing

[pytest](https://docs.pytest.org/) with coverage measurement. The 80% coverage gate
is enforced in CI. Coverage excludes the intentionally empty `mcp_server` and `agent`
packages -- only `banking_client` and `common` are measured.

Run manually:

```bash
uv run pytest --cov
```

### Pre-commit Hooks

The `.pre-commit-config.yaml` mirrors CI checks locally:

- `ruff-check` (with `--fix`) -- auto-fixes simple lint issues
- `ruff-format` -- enforces consistent formatting
- `mypy` -- strict type checking via the project virtualenv

These run automatically on `git commit` after `uv run pre-commit install`. To run
all hooks manually against the full codebase:

```bash
uv run pre-commit run --all-files
```
