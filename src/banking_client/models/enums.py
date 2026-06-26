"""Enumerations for FDX categorical fields.

Every categorical attribute on an FDX model is constrained to one of these enums rather
than a free string, so invalid values fail at parse time and downstream code can switch
exhaustively. Each value carries a docstring explaining why it exists. ``StrEnum`` members
compare equal to their string value, which keeps JSON (de)serialization transparent.

The sets here are intentional *subsets* of the larger FDX v6.5 enumerations — we model
only what the Core Exchange slice this project targets requires.
"""

from __future__ import annotations

from enum import StrEnum


class AccountType(StrEnum):
    """The kind of financial account.

    FDX defines many more types (MONEYMARKET, CD, CMA, …) grouped under account
    *categories* (deposit / loan / investment). This is the subset Open Banking MCP
    supports; income detection and balance logic branch on these five.
    """

    CHECKING = "CHECKING"
    """A transactional deposit account — the primary source for income detection."""
    SAVINGS = "SAVINGS"
    """An interest-bearing deposit account."""
    CREDIT_CARD = "CREDIT_CARD"
    """A revolving credit line; balances are typically amounts owed, not owned."""
    LOAN = "LOAN"
    """An installment loan (auto, personal, mortgage); balance is principal outstanding."""
    INVESTMENT = "INVESTMENT"
    """A brokerage / investment account holding securities."""


class AccountStatus(StrEnum):
    """Lifecycle state of an account.

    Subset of the FDX account status set (which also includes PENDINGOPEN, PENDINGCLOSE,
    DELINQUENT, …). Consumers use this to decide whether an account is actionable.
    """

    OPEN = "OPEN"
    """Active and usable."""
    CLOSED = "CLOSED"
    """Permanently closed; retained for history only."""
    RESTRICTED = "RESTRICTED"
    """Open but limited (e.g. frozen, hold placed) — reads may be allowed, writes not."""
    INACTIVE = "INACTIVE"
    """Dormant from lack of activity; not closed."""


class BalanceType(StrEnum):
    """Which balance a :class:`~banking_client.models.account.Balance` represents.

    These are the two balances Core Exchange needs. FDX models other balances
    (credit limit, interest, statement) in separate structures we do not include in
    this subset.
    """

    AVAILABLE = "AVAILABLE"
    """Funds usable right now — current balance minus holds and pending debits.

    This, not CURRENT, is what a user can actually spend.
    """
    CURRENT = "CURRENT"
    """The posted/ledger balance: settled transactions only, ignoring pending activity."""


class TransactionStatus(StrEnum):
    """Whether a transaction has settled.

    The PENDING → POSTED transition is the key signal for distinguishing authorized-but-
    unsettled activity from finalized ledger entries (see ``postedTimestamp`` on
    :class:`~banking_client.models.transaction.Transaction`).
    """

    PENDING = "PENDING"
    """Authorized but not yet settled; amount and timing may still change."""
    POSTED = "POSTED"
    """Settled and final on the ledger."""


class DebitCreditMemo(StrEnum):
    """Direction of money relative to the account (FDX ``debitCreditMemo``).

    Modeled explicitly because the sign of ``amount`` alone is ambiguous across FDX
    providers — this field is the authoritative direction. CREDIT into a deposit account
    is the basis of income detection.
    """

    DEBIT = "DEBIT"
    """Money leaving the account (a withdrawal, purchase, or payment)."""
    CREDIT = "CREDIT"
    """Money entering the account (a deposit, refund, or incoming transfer)."""
