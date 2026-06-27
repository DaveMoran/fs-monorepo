"""Generic offset-cursor pagination helpers.

The FDX offset-cursor scheme encodes the list offset as a URL-safe base64 string so callers
treat it as an opaque handle — they pass it back verbatim and never construct or interpret it
themselves.  These helpers are shared by every FDX endpoint that returns a paged list
(accounts, transactions, …).

Encoding
--------
``_encode_cursor(n)`` converts a non-negative integer *n* to a URL-safe base64 string with
padding stripped (RFC 4648 §5).  ``_decode_cursor(cursor)`` reverses this — it re-adds the
stripped padding, decodes the bytes, and parses an integer; any failure raises
:class:`~banking_client.client.errors.InvalidPageCursorError`.

Usage
-----
Call :func:`paginate` with the *full sorted* list of items, the desired ``limit``, and the
``page_key`` cursor (``None`` for the first page).  It returns a
:class:`~banking_client.models.pagination.PaginatedResponse` whose ``page.next_offset`` is
``None`` on the last page and ``page.prev_offset`` is ``None`` on the first page.
"""

from __future__ import annotations

import base64

from banking_client.client.errors import InvalidPageCursorError
from banking_client.models.pagination import PageMetadata, PaginatedResponse


def _encode_cursor(offset: int) -> str:
    """Encode a page offset as a URL-safe base64 cursor string.

    Args:
        offset: Non-negative integer offset into the full result list.

    Returns:
        URL-safe base64 string (no padding).
    """
    return base64.urlsafe_b64encode(str(offset).encode()).decode().rstrip("=")


def _decode_cursor(cursor: str, *, for_request: str) -> int:
    """Decode a URL-safe base64 cursor string to an integer offset.

    Args:
        cursor: The raw ``page_key`` value from the caller.
        for_request: Description of the calling operation for error context.

    Returns:
        Non-negative integer offset.

    Raises:
        InvalidPageCursorError: If *cursor* is not valid base64 or does not decode to a
            non-negative integer.
    """
    try:
        # Re-add stripped padding (base64 length must be a multiple of 4).
        padded = cursor + "=" * (-len(cursor) % 4)
        decoded = int(base64.urlsafe_b64decode(padded).decode())
        if decoded < 0:
            raise ValueError("negative offset")
        return decoded
    except Exception as exc:
        raise InvalidPageCursorError(cursor) from exc


def paginate[T](
    items: list[T],
    limit: int,
    page_key: str | None,
    *,
    for_request: str,
) -> PaginatedResponse[T]:
    """Slice *items* at the requested cursor position and wrap in a paginated envelope.

    Args:
        items: The full sorted list of items to paginate.
        limit: Maximum number of items to return in this page.
        page_key: Opaque cursor from a prior response; ``None`` means start from the beginning.
        for_request: Operation name used in :exc:`InvalidPageCursorError` context.

    Returns:
        A :class:`~banking_client.models.pagination.PaginatedResponse` containing the page
        window and metadata indicating whether further pages exist.

    Raises:
        InvalidPageCursorError: If *page_key* is provided but cannot be decoded.
    """
    start = _decode_cursor(page_key, for_request=for_request) if page_key is not None else 0
    window = items[start : start + limit]

    next_end = start + limit
    next_offset: str | None = _encode_cursor(next_end) if next_end < len(items) else None
    prev_offset: str | None = _encode_cursor(max(0, start - limit)) if start > 0 else None

    return PaginatedResponse[T](
        page=PageMetadata(
            total=len(items),
            next_offset=next_offset,
            prev_offset=prev_offset,
        ),
        items=window,
    )
