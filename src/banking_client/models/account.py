"""Account and Balance models.

Maps to the FDX v6.5 ``Account`` resource and its ``AccountBalance`` entries (Core
Exchange subset).
"""

from __future__ import annotations

from datetime import datetime

from banking_client.models.base import CurrencyCode, FDXBaseModel
from banking_client.models.enums import AccountStatus, AccountType, BalanceType
from banking_client.models.money import Money


class Balance(FDXBaseModel):
    """A single balance figure for an account (FDX ``AccountBalance``).

    An account reports several balances at once (available vs. current); ``balance_type``
    says which one this is, and ``amount`` carries the value with its currency.
    """

    balance_type: BalanceType
    """Which balance this is — AVAILABLE (spendable) or CURRENT (posted ledger)."""
    amount: Money
    """The balance value and its currency."""
    as_of_date: datetime
    """When this balance was computed.

    Balances are point-in-time; this timestamp tells consumers how fresh the figure is and
    lets two snapshots be ordered.
    """


class Account(FDXBaseModel):
    """A financial account owned by a customer (FDX ``Account``)."""

    id: str
    """Provider-assigned stable account identifier (FDX ``accountId``)."""
    account_type: AccountType
    """The kind of account — drives balance interpretation and income logic."""
    account_number_display: str
    """Masked account number safe to show a user (e.g. ``"****1234"``).

    FDX exposes only a display/masked form here; the full number is never carried in this
    model, by design.
    """
    nickname: str | None = None
    """Optional user-assigned label (e.g. ``"Joint Checking"``)."""
    status: AccountStatus
    """Lifecycle state — whether the account is open, closed, restricted, or inactive."""
    currency: CurrencyCode
    """The account's native denomination (ISO 4217). Individual balances also carry their
    own currency via :class:`Money`; this is the account-level default."""
    balances: list[Balance] = []
    """The account's reported balances (typically AVAILABLE and CURRENT)."""
