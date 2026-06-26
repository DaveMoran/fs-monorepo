"""Transaction model and its category object.

Maps to the FDX v6.5 ``Transaction`` resource (deposit / card activity, Core Exchange
subset).
"""

from __future__ import annotations

from datetime import datetime

from banking_client.models.base import FDXBaseModel
from banking_client.models.enums import DebitCreditMemo, TransactionStatus
from banking_client.models.money import Money


class TransactionCategory(FDXBaseModel):
    """A transaction's category, modeled as an FDX ``Category`` object rather than an enum.

    FDX carries category as a normalized object (an identifier plus a human-readable name
    from a categorization scheme), not a fixed enumeration. Modeling it as an object keeps
    us spec-faithful and lets the value space grow without code changes; income detection
    reads ``id`` / ``name`` rather than matching against a closed enum.
    """

    id: str
    """Stable category identifier from the categorization scheme."""
    name: str
    """Human-readable category label (e.g. ``"Payroll"``, ``"Groceries"``)."""


class Transaction(FDXBaseModel):
    """A single account transaction (FDX ``Transaction``)."""

    id: str
    """Provider-assigned stable transaction identifier (FDX ``transactionId``)."""
    account_id: str
    """Identifier of the :class:`~banking_client.models.account.Account` this belongs to."""
    amount: Money
    """The transaction amount and currency. Direction is given by ``debit_credit_memo``;
    do not rely on the sign of the amount alone."""
    posted_timestamp: datetime | None = None
    """When the transaction *settled* onto the ledger, or ``None`` if still PENDING.

    Diverges from ``transaction_timestamp``: a card swipe on Friday (transaction time)
    may not post until Monday (posted time). It is ``None`` while the transaction is
    PENDING and is set once it POSTs. Income detection keys recurring-deposit cadence off
    this field, because it reflects when funds actually became available.
    """
    transaction_timestamp: datetime
    """When the economic event occurred — the card swipe, transfer initiation, or check
    date.

    This is the *true* date of the activity and is always present, even while pending.
    It diverges from ``posted_timestamp`` by the settlement lag (and equals it only when
    a transaction posts same-day). Income detection uses this for the real economic date
    of a deposit while using ``posted_timestamp`` for availability cadence.
    """
    description: str
    """Raw transaction description as reported by the provider."""
    debit_credit_memo: DebitCreditMemo
    """Authoritative direction of money: DEBIT (out) or CREDIT (in)."""
    category: TransactionCategory | None = None
    """Optional categorization of the transaction; may be absent if uncategorized."""
    status: TransactionStatus
    """Whether the transaction is PENDING or POSTED."""
    payee: str | None = None
    """The merchant or counterparty, when the provider supplies a normalized name."""
