"""Transaction synthesis: the recurring backbone of each customer's history.

Generators return :class:`TxDraft` records (not finished models) so the orchestrator can sort a
whole account's activity by time and assign stable, sequential ids before materializing real
:class:`~banking_client.models.Transaction` instances. Amounts are always positive; direction is
carried by ``memo`` (DEBIT/CREDIT), matching the model's contract that the sign of the amount is
not authoritative.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from banking_client.models import (
    DebitCreditMemo,
    Transaction,
    TransactionCategory,
    TransactionStatus,
)
from fixtures.generator import catalog, schedule
from fixtures.generator.config import quantize, usd
from fixtures.generator.profiles import CustomerProfile


@dataclass
class TxDraft:
    """An unmaterialized transaction; gets a stable id once the account stream is ordered."""

    account_id: str
    when: datetime
    amount: Decimal
    description: str
    memo: DebitCreditMemo
    category: TransactionCategory | None
    payee: str | None
    status: TransactionStatus = TransactionStatus.POSTED
    posted: datetime | None = None

    def __post_init__(self) -> None:
        """Default a POSTED draft's posted timestamp to its transaction time (same-day settle)."""
        if self.status is TransactionStatus.POSTED and self.posted is None:
            self.posted = self.when


def materialize(draft: TxDraft, index: int) -> Transaction:
    """Turn a draft into a real :class:`Transaction` with a stable, ordered id."""
    return Transaction(
        id=f"{draft.account_id}-txn-{index:05d}",
        account_id=draft.account_id,
        amount=usd(draft.amount),
        posted_timestamp=draft.posted,
        transaction_timestamp=draft.when,
        description=draft.description,
        debit_credit_memo=draft.memo,
        category=draft.category,
        status=draft.status,
        payee=draft.payee,
    )


def _gauss_amount(rng: random.Random, mean: Decimal, stddev: Decimal) -> Decimal:
    """Draw a positive 2dp amount from a normal distribution (floor of $1.00)."""
    raw = quantize(Decimal(str(rng.gauss(float(mean), float(stddev)))))
    return max(Decimal("1.00"), raw)


def payroll_drafts(profile: CustomerProfile, account_id: str, start: datetime, end: datetime) -> list[TxDraft]:
    """Biweekly salary CREDITs, stepping to the raised amount partway through if configured."""
    spec = profile.payroll
    paydays = schedule.biweekly_occurrences(start, end)
    raise_at = start + (end - start) * spec.raise_after_fraction if spec.raise_amount is not None else None
    drafts: list[TxDraft] = []
    for payday in paydays:
        amount = spec.base_amount
        if spec.raise_amount is not None and raise_at is not None and payday >= raise_at:
            amount = spec.raise_amount
        drafts.append(
            TxDraft(
                account_id=account_id,
                when=payday,
                amount=amount,
                description=f"DIRECT DEPOSIT {spec.payee}",
                memo=DebitCreditMemo.CREDIT,
                category=catalog.PAYROLL,
                payee=spec.payee,
            )
        )
    return drafts


def bill_drafts(
    profile: CustomerProfile, account_id: str, rng: random.Random, start: datetime, end: datetime
) -> list[TxDraft]:
    """Recurring monthly bill DEBITs, with optional small amount jitter (e.g. utilities)."""
    drafts: list[TxDraft] = []
    for bill in profile.bills:
        for occurrence in schedule.monthly_occurrences(start, end, bill.day_of_month):
            amount = bill.amount
            if bill.jitter > 0:
                wobble = Decimal(str(rng.uniform(float(-bill.jitter), float(bill.jitter))))
                amount = max(Decimal("1.00"), quantize(bill.amount + wobble))
            drafts.append(
                TxDraft(
                    account_id=account_id,
                    when=occurrence,
                    amount=amount,
                    description=f"{bill.payee} PAYMENT",
                    memo=DebitCreditMemo.DEBIT,
                    category=bill.category,
                    payee=bill.payee,
                )
            )
    return drafts


def discretionary_drafts(
    profile: CustomerProfile, account_id: str, rng: random.Random, start: datetime, end: datetime
) -> list[TxDraft]:
    """Variable everyday spend DEBITs scattered through each month per category."""
    drafts: list[TxDraft] = []
    for spec in profile.discretionary:
        merchants = catalog.MERCHANTS[spec.category.id]
        for month_start in schedule.month_anchors(start, end):
            for _ in range(spec.monthly_count):
                day = rng.randint(1, 27)
                when = month_start.replace(day=day)
                if not (start <= when <= end):
                    continue
                payee = merchants[rng.randrange(len(merchants))]
                drafts.append(
                    TxDraft(
                        account_id=account_id,
                        when=when,
                        amount=_gauss_amount(rng, spec.amount_mean, spec.amount_stddev),
                        description=f"PURCHASE {payee}",
                        memo=DebitCreditMemo.DEBIT,
                        category=spec.category,
                        payee=payee,
                    )
                )
    return drafts


def savings_transfer_drafts(
    checking_id: str, savings_id: str, amount: Decimal, start: datetime, end: datetime
) -> list[TxDraft]:
    """Monthly internal transfer: a DEBIT on checking paired with a CREDIT on savings.

    The savings-side CREDIT is a deliberate near-miss for income detection (a recurring inbound
    that is a transfer, not earnings).
    """
    drafts: list[TxDraft] = []
    for occurrence in schedule.monthly_occurrences(start, end, day_of_month=3):
        drafts.append(
            TxDraft(
                account_id=checking_id,
                when=occurrence,
                amount=amount,
                description="TRANSFER TO SAVINGS",
                memo=DebitCreditMemo.DEBIT,
                category=catalog.TRANSFER,
                payee="INTERNAL TRANSFER",
            )
        )
        drafts.append(
            TxDraft(
                account_id=savings_id,
                when=occurrence,
                amount=amount,
                description="TRANSFER FROM CHECKING",
                memo=DebitCreditMemo.CREDIT,
                category=catalog.TRANSFER,
                payee="INTERNAL TRANSFER",
            )
        )
    return drafts
