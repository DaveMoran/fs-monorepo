"""The :class:`Money` value object — an amount paired with its currency.

FDX represents money as a bare numeric ``amount`` alongside a currency carried elsewhere
on the resource. We bundle the two into one reusable value object so an amount can never
travel without its currency, and so the ``Decimal`` choice (see
:mod:`banking_client.models.base`) is enforced in exactly one place.
"""

from __future__ import annotations

from decimal import Decimal

from banking_client.models.base import CurrencyCode, FDXBaseModel


class Money(FDXBaseModel):
    """A monetary amount in a specific currency.

    ``value`` is always a :class:`~decimal.Decimal` — never ``float`` — for exact base-10
    arithmetic (a ``float`` ledger drifts off the cent). Pydantic serializes it to a JSON
    string to preserve precision on round-trip.
    """

    value: Decimal
    """The amount, as an exact ``Decimal``. May be negative to express direction."""
    currency: CurrencyCode
    """ISO 4217 code denominating ``value`` (e.g. ``"USD"``)."""
