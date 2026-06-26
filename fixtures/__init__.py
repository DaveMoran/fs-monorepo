"""Dev-only synthetic FDX data generator (NOT shipped product).

This top-level package lives outside ``src/`` on purpose: it is a stand-in for the real FDX
data source used until live credentials exist (~Week 20). It imports the real Pydantic models
from :mod:`banking_client.models` and generates spec-conformant fixtures through them.

The package is held to the same mypy/ruff standards as ``src/`` but is excluded from the
coverage gate and is never bundled into the shipped wheel. It can be deleted in Week 20 by
reverting only the ``pyproject.toml`` tooling entries that reference ``fixtures`` — no ``src/``
change required.
"""
