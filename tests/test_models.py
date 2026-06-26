"""Tests for the FDX data models.

Exercises construction, camelCase/snake_case round-tripping, Decimal precision, currency
validation, the generic paginated envelope, and the PENDING/POSTED timestamp invariant.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError

from banking_client.models import (
    Account,
    AccountStatus,
    AccountType,
    Balance,
    BalanceType,
    Customer,
    DebitCreditMemo,
    FDXError,
    Money,
    PageMetadata,
    PaginatedResponse,
    Transaction,
    TransactionCategory,
    TransactionStatus,
)


def _money(value: str = "100.00") -> Money:
    return Money(value=Decimal(value), currency="USD")


def _balance() -> Balance:
    return Balance(
        balance_type=BalanceType.AVAILABLE,
        amount=_money(),
        as_of_date=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _account() -> Account:
    return Account(
        id="acct-1",
        account_type=AccountType.CHECKING,
        account_number_display="****1234",
        status=AccountStatus.OPEN,
        currency="USD",
        balances=[_balance()],
    )


def test_every_model_constructs() -> None:
    """Each model and enum can be instantiated with valid data."""
    account = _account()
    assert account.account_type is AccountType.CHECKING
    assert account.balances[0].balance_type is BalanceType.AVAILABLE

    customer = Customer(id="cust-1", name="Ada Lovelace", accounts=[account])
    assert customer.accounts[0].id == "acct-1"

    error = FDXError(code="rateLimited", message="Too many requests")
    assert error.debug_message is None


def test_camelcase_round_trip() -> None:
    """Models parse FDX camelCase input and re-emit camelCase via by_alias."""
    payload = {
        "id": "txn-1",
        "accountId": "acct-1",
        "amount": {"value": "42.50", "currency": "USD"},
        "transactionTimestamp": "2026-01-02T10:00:00Z",
        "postedTimestamp": "2026-01-03T00:00:00Z",
        "description": "Coffee",
        "debitCreditMemo": "DEBIT",
        "status": "POSTED",
        "category": {"id": "5812", "name": "Dining"},
        "payee": "Blue Bottle",
    }
    txn = Transaction.model_validate(payload)
    assert txn.account_id == "acct-1"
    assert txn.debit_credit_memo is DebitCreditMemo.DEBIT
    assert isinstance(txn.category, TransactionCategory)

    dumped = txn.model_dump(by_alias=True)
    assert "accountId" in dumped and "account_id" not in dumped
    assert dumped["debitCreditMemo"] == "DEBIT"


def test_snake_case_construction_allowed() -> None:
    """populate_by_name lets Python code build models with snake_case field names."""
    txn = Transaction(
        id="txn-2",
        account_id="acct-1",
        amount=_money("9.99"),
        transaction_timestamp=datetime(2026, 1, 2, tzinfo=UTC),
        description="App Store",
        debit_credit_memo=DebitCreditMemo.DEBIT,
        status=TransactionStatus.POSTED,
    )
    assert txn.account_id == "acct-1"


def test_decimal_precision_survives_json_round_trip() -> None:
    """Money stays an exact Decimal and does not degrade to float through JSON."""
    money = _money("100.10")
    assert isinstance(money.value, Decimal)

    restored = Money.model_validate_json(money.model_dump_json())
    assert restored.value == Decimal("100.10")
    assert isinstance(restored.value, Decimal)
    # Pydantic emits Decimal as a JSON string to preserve precision.
    assert '"100.10"' in money.model_dump_json()


def test_invalid_currency_rejected() -> None:
    """Currency must be a 3-letter uppercase ISO 4217 code."""
    for bad in ["usd", "US", "USDD", "12$"]:
        with pytest.raises(ValidationError):
            Money(value=Decimal("1"), currency=bad)


def test_paginated_response_generic() -> None:
    """PaginatedResponse[T] parses page metadata and a typed item list."""
    page = PaginatedResponse[Account].model_validate(
        {
            "page": {"total": 1, "nextOffset": None, "prevOffset": None},
            "items": [_account().model_dump(by_alias=True)],
        }
    )
    assert isinstance(page.page, PageMetadata)
    assert page.page.total == 1
    assert isinstance(page.items[0], Account)
    assert page.items[0].id == "acct-1"


def test_pending_transaction_has_no_posted_timestamp() -> None:
    """A PENDING transaction defaults postedTimestamp to None; a POSTED one sets it."""
    pending = Transaction(
        id="txn-pending",
        account_id="acct-1",
        amount=_money("20.00"),
        transaction_timestamp=datetime(2026, 1, 2, tzinfo=UTC),
        description="Pending hold",
        debit_credit_memo=DebitCreditMemo.DEBIT,
        status=TransactionStatus.PENDING,
    )
    assert pending.posted_timestamp is None

    posted = pending.model_copy(
        update={
            "status": TransactionStatus.POSTED,
            "posted_timestamp": datetime(2026, 1, 3, tzinfo=UTC),
        }
    )
    assert posted.posted_timestamp is not None


def test_unknown_fields_ignored() -> None:
    """Unmodeled FDX fields are ignored rather than raising (extra='ignore')."""
    error = FDXError.model_validate({"code": "x", "message": "y", "unmodeledFdxField": "ignored"})
    assert not hasattr(error, "unmodeledFdxField")
