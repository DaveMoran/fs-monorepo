"""Orchestration: assemble whole customer datasets from profiles.

For each profile this collects every account's draft transactions, orders them by time, assigns
stable ids, derives AVAILABLE/CURRENT balances consistent with that history, and packages the
result as a :class:`~banking_client.models.Customer` plus one
:class:`~banking_client.models.PaginatedResponse` of transactions per account — exactly the
shapes the four MCP tools will serve.

A single RNG is threaded through all customers in stable order, so the entire dataset is a pure
function of the seed.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from banking_client.models import (
    Account,
    AccountType,
    Balance,
    Customer,
    DebitCreditMemo,
    PageMetadata,
    PaginatedResponse,
    Transaction,
    TransactionStatus,
)
from fixtures.generator import transactions as tx
from fixtures.generator import tricky
from fixtures.generator.accounts import build_account, build_balances
from fixtures.generator.config import GenerationConfig, new_rng
from fixtures.generator.profiles import PROFILES, AccountSpec, CustomerProfile
from fixtures.generator.schedule import window_start

SAVINGS_TRANSFER = Decimal("400.00")
"""Fixed monthly checking→savings transfer for customers holding a savings account."""

NON_CHECKING_OPENING: dict[AccountType, Decimal] = {
    AccountType.SAVINGS: Decimal("6000.00"),
    AccountType.CREDIT_CARD: Decimal("750.00"),
    AccountType.INVESTMENT: Decimal("48000.00"),
}
"""Opening balances for accounts that carry no generated transaction stream."""


@dataclass
class CustomerDataset:
    """A fully built customer plus their per-account transaction responses."""

    customer: Customer
    transactions: dict[str, PaginatedResponse[Transaction]]


def _account_id(profile: CustomerProfile, spec: AccountSpec) -> str:
    return f"{profile.customer_id}-{spec.suffix}"


def _opening_for(profile: CustomerProfile, spec: AccountSpec) -> Decimal:
    if spec.is_primary:
        return profile.opening_balance
    return NON_CHECKING_OPENING.get(spec.account_type, Decimal("0.00"))


def _collect_drafts(profile: CustomerProfile, rng: random.Random, start: datetime, end: datetime) -> list[tx.TxDraft]:
    primary = next(account for account in profile.accounts if account.is_primary)
    primary_id = _account_id(profile, primary)
    drafts: list[tx.TxDraft] = []
    drafts += tx.payroll_drafts(profile, primary_id, start, end)
    drafts += tx.bill_drafts(profile, primary_id, rng, start, end)
    drafts += tx.discretionary_drafts(profile, primary_id, rng, start, end)

    savings = next((a for a in profile.accounts if a.account_type is AccountType.SAVINGS), None)
    if savings is not None:
        drafts += tx.savings_transfer_drafts(primary_id, _account_id(profile, savings), SAVINGS_TRANSFER, start, end)

    if profile.include_venmo_fake_income:
        drafts += tricky.venmo_fake_income_drafts(primary_id, rng, start, end)
    if profile.include_freelance:
        drafts += tricky.freelance_drafts(primary_id, rng, start, end)
    if profile.include_refund:
        drafts.append(tricky.refund_draft(primary_id, rng, start, end))
    if profile.include_large_purchase:
        drafts.append(tricky.large_purchase_draft(primary_id, rng, start, end))
    if profile.include_pending:
        drafts += tricky.pending_drafts(primary_id, rng, end)
    return drafts


def _balances_for(opening: Decimal, txns: list[Transaction], as_of: datetime) -> list[Balance]:
    """Derive CURRENT (posted only) and AVAILABLE (posted minus pending holds) from history."""
    current = opening
    pending_delta = Decimal("0")
    for txn in txns:
        signed = txn.amount.value if txn.debit_credit_memo is DebitCreditMemo.CREDIT else -txn.amount.value
        if txn.status is TransactionStatus.POSTED:
            current += signed
        else:
            pending_delta += signed
    return build_balances(current=current, available=current + pending_delta, as_of=as_of)


def _paginate(txns: list[Transaction]) -> PaginatedResponse[Transaction]:
    return PaginatedResponse[Transaction](page=PageMetadata(total=len(txns)), items=txns)


def build_customer(profile: CustomerProfile, config: GenerationConfig, rng: random.Random) -> CustomerDataset:
    """Build one customer's accounts and per-account transaction histories."""
    start = window_start(config.anchor_date, config.history_months)
    end = config.anchor_date

    by_account: dict[str, list[tx.TxDraft]] = {_account_id(profile, spec): [] for spec in profile.accounts}
    for draft in _collect_drafts(profile, rng, start, end):
        by_account[draft.account_id].append(draft)

    materialized: dict[str, list[Transaction]] = {}
    for account_id, drafts in by_account.items():
        drafts.sort(key=lambda draft: draft.when)
        materialized[account_id] = [tx.materialize(draft, index) for index, draft in enumerate(drafts)]

    accounts: list[Account] = []
    responses: dict[str, PaginatedResponse[Transaction]] = {}
    for spec in profile.accounts:
        account_id = _account_id(profile, spec)
        txns = materialized[account_id]
        balances = _balances_for(_opening_for(profile, spec), txns, end)
        accounts.append(build_account(spec, profile.customer_id, balances))
        responses[account_id] = _paginate(txns)

    customer = Customer(id=profile.customer_id, name=profile.name, accounts=accounts)
    return CustomerDataset(customer=customer, transactions=responses)


def build_dataset(config: GenerationConfig) -> list[CustomerDataset]:
    """Build the full dataset: the first ``config.num_customers`` archetypes, in order."""
    rng = new_rng(config)
    return [build_customer(profile, config, rng) for profile in PROFILES[: config.num_customers]]
