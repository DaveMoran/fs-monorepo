"""FDX error-response model.

Maps to the FDX v6.5 ``Error`` schema (Core Exchange subset: the three fields callers
need). This is the response *body* an FDX API returns on failure; it is distinct from the
Python exception types in :mod:`common.errors`, which represent client-side failures.
"""

from __future__ import annotations

from banking_client.models.base import FDXBaseModel


class FDXError(FDXBaseModel):
    """A structured error returned by an FDX API (FDX ``Error``)."""

    code: str
    """Stable, machine-readable error code for programmatic handling."""
    message: str
    """Human-readable description safe to surface to an end user."""
    debug_message: str | None = None
    """Optional developer-facing detail (stack hints, internal context).

    May be absent and should never be shown to end users.
    """
