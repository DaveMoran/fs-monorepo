"""Generic paginated-response envelope.

Maps to the FDX v6.5 paged-list pattern: a ``page`` metadata element plus an array of the
resource. FDX names that array after the resource (``accounts``, ``transactions``); we use
a generic ``items`` field so a single envelope type serves every resource.
"""

from __future__ import annotations

from banking_client.models.base import FDXBaseModel


class PageMetadata(FDXBaseModel):
    """Pagination metadata for a list response (FDX ``page`` element).

    Offset-based: ``next_offset`` is the cursor to request the following page, and is
    ``None`` on the last page.
    """

    total: int | None = None
    """Total number of items across all pages, when the provider reports it."""
    next_offset: str | None = None
    """Cursor for the next page; ``None`` when there are no further pages."""
    prev_offset: str | None = None
    """Cursor for the previous page; ``None`` on the first page."""


class PaginatedResponse[T](FDXBaseModel):
    """A page of results: pagination metadata plus the items themselves.

    Parameterized by the resource type, e.g. ``PaginatedResponse[Account]`` or
    ``PaginatedResponse[Transaction]``.
    """

    page: PageMetadata
    """Pagination metadata for this response."""
    items: list[T] = []
    """The resources on this page."""
