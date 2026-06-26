"""Deliberately tricky transactions that defeat naive income/spending heuristics.

Each generator here injects an edge case the detection logic must get right:

- **Venmo-style fake income** — a recurring inbound CREDIT that is a P2P transfer, not earnings.
  Defeats "any CREDIT is income."
- **Irregular freelance income** — genuine income that arrives off the biweekly cadence with
  varying amounts. Defeats "income must be regular and equal."
- **Refund** — an inbound CREDIT that reverses a prior purchase. Defeats double-counting refunds
  as income.
- **Large one-off purchase** — a rare big DEBIT that skews spend averages.
- **Pending transactions** — recent activity with ``posted_timestamp is None`` /
  ``status=PENDING``. Defeats cadence logic that assumes a posted timestamp.

The mid-history payroll raise (another tricky case) lives in
:func:`fixtures.generator.transactions.payroll_drafts`, since it is a property of the payroll
stream itself.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from decimal import Decimal

from banking_client.models import DebitCreditMemo, TransactionStatus
from fixtures.generator import catalog
from fixtures.generator.config import quantize
from fixtures.generator.transactions import TxDraft


def _spread_dates(rng: random.Random, start: datetime, end: datetime, count: int) -> list[datetime]:
    span = (end - start).days
    days = sorted(rng.randint(0, span) for _ in range(count))
    return [start + timedelta(days=offset) for offset in days]


def venmo_fake_income_drafts(account_id: str, rng: random.Random, start: datetime, end: datetime) -> list[TxDraft]:
    """Irregular Venmo cashouts categorized as TRANSFER — looks like income, isn't."""
    drafts: list[TxDraft] = []
    for when in _spread_dates(rng, start, end, count=5):
        amount = quantize(Decimal(str(rng.uniform(45, 220))))
        drafts.append(
            TxDraft(
                account_id=account_id,
                when=when,
                amount=amount,
                description="VENMO CASHOUT",
                memo=DebitCreditMemo.CREDIT,
                category=catalog.TRANSFER,
                payee="VENMO",
            )
        )
    return drafts


def freelance_drafts(account_id: str, rng: random.Random, start: datetime, end: datetime) -> list[TxDraft]:
    """Irregular, variable-amount freelance CREDITs — real income, off-cadence."""
    payees = ("UPWORK", "FIVERR", "DIRECT CLIENT")
    drafts: list[TxDraft] = []
    for when in _spread_dates(rng, start, end, count=7):
        amount = quantize(Decimal(str(rng.uniform(300, 1400))))
        payee = payees[rng.randrange(len(payees))]
        drafts.append(
            TxDraft(
                account_id=account_id,
                when=when,
                amount=amount,
                description=f"FREELANCE PAYMENT {payee}",
                memo=DebitCreditMemo.CREDIT,
                category=catalog.FREELANCE,
                payee=payee,
            )
        )
    return drafts


def refund_draft(account_id: str, rng: random.Random, start: datetime, end: datetime) -> TxDraft:
    """A single inbound refund CREDIT reversing an earlier purchase."""
    when = _spread_dates(rng, start, end, count=1)[0]
    amount = quantize(Decimal(str(rng.uniform(40, 260))))
    return TxDraft(
        account_id=account_id,
        when=when,
        amount=amount,
        description="REFUND AMAZON",
        memo=DebitCreditMemo.CREDIT,
        category=catalog.REFUND,
        payee="Amazon",
    )


def large_purchase_draft(account_id: str, rng: random.Random, start: datetime, end: datetime) -> TxDraft:
    """A rare large one-off DEBIT that skews naive spend averages."""
    when = _spread_dates(rng, start, end, count=1)[0]
    amount = quantize(Decimal(str(rng.uniform(1600, 3400))))
    return TxDraft(
        account_id=account_id,
        when=when,
        amount=amount,
        description="PURCHASE BIG TICKET ELECTRONICS",
        memo=DebitCreditMemo.DEBIT,
        category=catalog.SHOPPING,
        payee="Best Buy",
    )


def pending_drafts(account_id: str, rng: random.Random, end: datetime) -> list[TxDraft]:
    """A couple of very recent DEBITs left PENDING (no posted timestamp)."""
    drafts: list[TxDraft] = []
    for days_ago in (1, 2):
        when = end - timedelta(days=days_ago)
        amount = quantize(Decimal(str(rng.uniform(15, 90))))
        drafts.append(
            TxDraft(
                account_id=account_id,
                when=when,
                amount=amount,
                description="PENDING PURCHASE SWEETGREEN",
                memo=DebitCreditMemo.DEBIT,
                category=catalog.DINING,
                payee="Sweetgreen",
                status=TransactionStatus.PENDING,
                posted=None,
            )
        )
    return drafts
