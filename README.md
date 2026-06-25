# Open Banking MCP Capstone

![CI](https://github.com/DaveMoran/fs-monorepo/actions/workflows/ci.yml/badge.svg)

A production-grade Python repository for an Open Banking Model Context Protocol (MCP)
capstone. This milestone establishes the repository bones -- a four-package src-layout
skeleton, strict tooling, CI/CD, pre-commit hooks, and contributor docs -- that later
phases will fill with an FDX API client, an MCP server, and an agent loop.

Built to demonstrate enterprise-grade product-engineering posture from the first commit:
strict typing, lint/format, a Python 3.12/3.13 CI matrix, an 80% coverage gate, and
pre-commit hooks all pass green before any business logic exists.

## Quick Start

```bash
git clone https://github.com/DaveMoran/fs-monorepo.git
cd fs-monorepo
uv sync --all-extras --dev
```

Copy the environment template and fill in values as needed:

```bash
cp .env.example .env
```

## Development

Run the quality checks locally:

```bash
# Lint
uv run ruff check .

# Format check
uv run ruff format --check .

# Type check (strict mode)
uv run mypy

# Tests with coverage
uv run pytest --cov

# Install pre-commit hooks (runs ruff + mypy on each commit)
uv run pre-commit install
```

All tool configuration lives in `pyproject.toml` -- no flags to remember.

## Architecture

The project uses a `src/` layout with four packages:

| Package | Purpose | Status |
|---------|---------|--------|
| `banking_client` | FDX API client for Open Banking data retrieval | Skeleton |
| `mcp_server` | MCP server exposing banking tools to LLM agents | Skeleton (empty) |
| `agent` | Agent loop orchestrating MCP tool calls | Skeleton (empty) |
| `common` | Shared utilities: config, logging, error hierarchy | Scaffold with stubs |

`mcp_server` and `agent` are intentionally empty skeletons -- they will be implemented
in later phases. `common` provides typed stubs for configuration, structured logging,
and a domain error hierarchy that other packages will use.

## Capstone Spec

<!-- spec excerpt placeholder -->

Capstone specification excerpt will be added here once the project progresses beyond
the repository scaffolding phase.

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
