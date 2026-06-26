"""Client-layer error types for the FDX account wrapper.

These exceptions represent failure modes that are distinct from auth-layer errors
(:class:`~common.errors.AuthenticationError`, :class:`~common.errors.AuthorizationError`).
They arise *after* a valid, authorized request reaches the data layer.

Taxonomy
--------
- :class:`AccountNotFoundError` — the requested account id is within the token's consent scope
  but is absent from the data source. Maps to HTTP 404 in an API context.
- :class:`InvalidPageCursorError` — the ``page_key`` cursor supplied to a list operation could
  not be decoded. Maps to HTTP 400 in an API context.

All errors subclass :class:`~common.errors.OpenBankingError` so callers can catch the full
banking-layer error hierarchy with a single ``except OpenBankingError`` clause.
"""

from __future__ import annotations

from common.errors import OpenBankingError


class AccountNotFoundError(OpenBankingError):
    """Raised when an authorized account id is absent from the data source.

    Distinct from :class:`~common.errors.AuthorizationError`: the token *is* permitted to
    access this account id (it appears in the consent scope), but the data source returned
    no record for it. This can happen when the consent registry and the data store are out
    of sync — e.g. an account referenced in ``consents.json`` has been closed or removed.

    Attributes:
        account_id: The FDX account id that was not found.
    """

    def __init__(self, account_id: str) -> None:
        """Build a structured message from the missing account id.

        Args:
            account_id: The FDX account id that could not be located.
        """
        super().__init__(f"account not found: {account_id!r}")
        self.account_id = account_id


class InvalidPageCursorError(OpenBankingError):
    """Raised when a ``page_key`` cursor cannot be decoded.

    The pagination cursor is an opaque URL-safe base64–encoded offset. This error is raised
    when the supplied value is not valid base64, does not decode to an integer, or decodes to
    a negative offset. Callers should treat this as a bad-request error and not retry with the
    same cursor.

    Attributes:
        cursor: The raw ``page_key`` string that failed to decode.
    """

    def __init__(self, cursor: str) -> None:
        """Build a structured message from the invalid cursor.

        Args:
            cursor: The raw ``page_key`` value that could not be decoded.
        """
        super().__init__(f"invalid page cursor: {cursor!r}")
        self.cursor = cursor
