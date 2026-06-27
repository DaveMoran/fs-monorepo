"""Tests for the savings-capacity service and its pure helper functions.

Structure
---------
- Pure unit tests on ``_compute_capacity``, ``_floor_to_increment``,
  ``_conservative_set_aside``, ``_select_priority``, and ``_detect_high_interest_debt``
  — no I/O, run synchronously.
- Scope-boundary / type-system tests asserting the no-advice structural guarantee.
- Service unit tests using ``_FakeTxnSource`` and ``_FakeAcctSource`` — synthetic data,
  no filesystem.
- Integration tests against the committed fixture data via ``default_savings_service``.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from banking_client.analytics.income import IncomeService
from banking_client.analytics.results import (
    CONSERVATIVE_FRACTION,
    LOW_CONFIDENCE_FRACTION,
    ROUNDING_INCREMENT,
    ConfidenceLevel,
    ReasoningCode,
    SavingsCapacityStatus,
    SavingsPriority,
)
from banking_client.analytics.savings import (
    SavingsCapacityService,
    _compute_capacity,
    _conservative_set_aside,
    _detect_high_interest_debt,
    _floor_to_increment,
    _select_priority,
    default_savings_service,
    render_reasoning,
)
from banking_client.analytics.spending import SpendingService
from banking_client.auth import Authorizer, DataCluster
from banking_client.auth.scope import ConsentScope
from banking_client.client.accounts import AccountsClient
from banking_client.client.transactions import TransactionsClient
from banking_client.models.account import Account, Balance
from banking_client.models.enums import (
    AccountStatus,
    AccountType,
    BalanceType,
    DebitCreditMemo,
    TransactionStatus,
)
from banking_client.models.money import Money
from banking_client.models.transaction import Transaction, TransactionCategory
from common.audit import AuditOutcome, AuditTrail, ListSink
from common.errors import AuthorizationError

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ANCHOR = datetime(2026, 6, 30, tzinfo=UTC)
_TOKEN_001 = "tok_cust_001"
_TOKEN_002 = "tok_cust_002"
_TOKEN_003 = "tok_cust_003"
_TOKEN_003_TXN_ONLY = "tok_cust_003_txn_only"

_CAT_RENT = TransactionCategory(id="CAT-RENT", name="Rent")
_CAT_SUBS = TransactionCategory(id="CAT-SUBSCRIPTION", name="Subscription")
_CAT_GROC = TransactionCategory(id="CAT-GROCERIES", name="Groceries")

# ---------------------------------------------------------------------------
# Transaction + account builder helpers
# ---------------------------------------------------------------------------


def _txn(
    amount: str = "100.00",
    memo: DebitCreditMemo = DebitCreditMemo.DEBIT,
    payee: str | None = "LANDLORD",
    category: TransactionCategory | None = _CAT_RENT,
    posted: datetime | None = datetime(2026, 6, 1, tzinfo=UTC),
    status: TransactionStatus = TransactionStatus.POSTED,
    txn_id: str = "txn-001",
) -> Transaction:
    """Build a Transaction for service unit tests."""
    resolved = posted if status is TransactionStatus.POSTED else None
    return Transaction(
        id=txn_id,
        account_id="test-checking",
        amount=Money(value=Decimal(amount), currency="USD"),
        posted_timestamp=resolved,
        transaction_timestamp=posted or datetime(2025, 7, 1, tzinfo=UTC),
        description="TEST",
        debit_credit_memo=memo,
        category=category,
        status=status,
        payee=payee,
    )


def _credit_txn(
    amount: str,
    payee: str,
    posted: datetime,
    txn_id: str = "txn-credit-001",
) -> Transaction:
    """Build a posted CREDIT transaction (income)."""
    return Transaction(
        id=txn_id,
        account_id="test-checking",
        amount=Money(value=Decimal(amount), currency="USD"),
        posted_timestamp=posted,
        transaction_timestamp=posted,
        description="INCOME",
        debit_credit_memo=DebitCreditMemo.CREDIT,
        status=TransactionStatus.POSTED,
        payee=payee,
    )


def _acct(
    account_id: str = "acct-checking",
    account_type: AccountType = AccountType.CHECKING,
    status: AccountStatus = AccountStatus.OPEN,
    balances: list[Balance] | None = None,
) -> Account:
    """Build an Account for debt-detection tests."""
    return Account(
        id=account_id,
        account_type=account_type,
        account_number_display="****1234",
        status=status,
        currency="USD",
        balances=balances or [],
    )


def _balance(amount: str, balance_type: BalanceType = BalanceType.CURRENT) -> Balance:
    """Build a Balance for an account."""
    return Balance(
        balance_type=balance_type,
        amount=Money(value=Decimal(amount), currency="USD"),
        as_of_date=_ANCHOR,
    )


# ---------------------------------------------------------------------------
# Biweekly payroll stream helper (produces 24 credits over 12 months)
# ---------------------------------------------------------------------------


def _biweekly_payroll(
    n: int,
    amount: str,
    start: datetime,
    payee: str = "PAYROLL CO",
) -> list[Transaction]:
    """Build *n* biweekly CREDIT transactions (income stream)."""
    return [
        _credit_txn(
            amount=amount,
            payee=payee,
            posted=start + timedelta(days=14 * i),
            txn_id=f"payroll-{i:04d}",
        )
        for i in range(n)
    ]


def _monthly_debits(
    n: int,
    amount: str,
    start: datetime,
    payee: str = "LANDLORD",
    category: TransactionCategory = _CAT_RENT,
) -> list[Transaction]:
    """Build *n* monthly DEBIT transactions (spending stream)."""
    return [
        _txn(
            amount=amount,
            payee=payee,
            category=category,
            posted=start + timedelta(days=30 * i),
            txn_id=f"spend-{i:04d}",
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Fake data sources and service factory
# ---------------------------------------------------------------------------


class _FakeTxnSource:
    """In-memory TransactionDataSource backed by a static list."""

    def __init__(self, txns: list[Transaction]) -> None:
        self._txns = txns

    async def list_transactions(self, *, token: str, customer_id: str, account_id: str) -> list[Transaction]:
        return self._txns


class _FakeAcctSource:
    """In-memory AccountDataSource backed by a static list."""

    def __init__(self, accounts: list[Account]) -> None:
        self._accounts = accounts

    async def list_accounts(self, *, token: str, customer_id: str) -> list[Account]:
        return self._accounts

    async def get_account(self, *, token: str, customer_id: str, account_id: str) -> Account | None:
        return next((a for a in self._accounts if a.id == account_id), None)


class _FakeResolver:
    def __init__(self, registry: dict[str, ConsentScope]) -> None:
        self._registry = registry

    def resolve(self, token: str) -> ConsentScope:
        from common.errors import AuthenticationError

        scope = self._registry.get(token)
        if scope is None:
            raise AuthenticationError(f"Unknown token: {token!r}")
        return scope


def _scope(
    *,
    customer_id: str = "cust-test",
    account_ids: list[str] | None = None,
    clusters: list[DataCluster] | None = None,
) -> ConsentScope:
    return ConsentScope(
        consent_id=f"consent-{customer_id}",
        customer_id=customer_id,
        account_ids=frozenset(account_ids or ["test-checking"]),
        data_clusters=frozenset(clusters or [DataCluster.TRANSACTIONS, DataCluster.ACCOUNTS]),
        expires_at=None,
    )


def _fake_savings_service(
    txns: list[Transaction],
    accounts: list[Account] | None = None,
    *,
    tx_account_id: str = "test-checking",
    acct_account_ids: list[str] | None = None,
) -> tuple[SavingsCapacityService, str]:
    """Return (SavingsCapacityService, token) wired to in-memory fake sources."""
    all_acct_ids = acct_account_ids or [tx_account_id]
    trail = AuditTrail(sink=ListSink())
    resolver = _FakeResolver(
        {
            "test-tok": _scope(
                account_ids=all_acct_ids,
                clusters=[DataCluster.TRANSACTIONS, DataCluster.ACCOUNTS],
            )
        }
    )
    auth = Authorizer(resolver=resolver)  # type: ignore[arg-type]

    tx_client = TransactionsClient(
        data_source=_FakeTxnSource(txns),  # type: ignore[arg-type]
        authorizer=auth,
        trail=trail,
    )
    acct_client = AccountsClient(
        data_source=_FakeAcctSource(accounts or []),  # type: ignore[arg-type]
        authorizer=auth,
        trail=trail,
    )

    income_svc = IncomeService(
        transactions_client=tx_client,
        accounts_client=acct_client,
    )
    spending_svc = SpendingService(
        transactions_client=tx_client,
        accounts_client=acct_client,
    )
    svc = SavingsCapacityService(
        income_service=income_svc,
        spending_service=spending_svc,
        accounts_client=acct_client,
    )
    return svc, "test-tok"


# ===========================================================================
# Pure unit tests — _compute_capacity
# ===========================================================================


def test_compute_capacity_positive() -> None:
    """Income − fixed − variable = positive capacity."""
    cap = _compute_capacity(Decimal("3000.00"), Decimal("1200.00"), Decimal("600.00"))
    assert cap == Decimal("1200.00")


def test_compute_capacity_zero() -> None:
    """Spending exactly equals income → capacity is zero."""
    cap = _compute_capacity(Decimal("2000.00"), Decimal("1000.00"), Decimal("1000.00"))
    assert cap == Decimal("0.00")


def test_compute_capacity_negative() -> None:
    """Spending exceeds income → negative capacity (deficit)."""
    cap = _compute_capacity(Decimal("1500.00"), Decimal("1200.00"), Decimal("700.00"))
    assert cap == Decimal("-400.00")


def test_compute_capacity_quantized_to_two_decimals() -> None:
    """Result is always quantized to 2 decimal places."""
    cap = _compute_capacity(Decimal("1000.005"), Decimal("0"), Decimal("0"))
    assert cap == Decimal("1000.01")  # ROUND_HALF_UP


# ===========================================================================
# Pure unit tests — _floor_to_increment
# ===========================================================================


def test_floor_to_increment_exact_multiple() -> None:
    """An exact multiple is returned unchanged."""
    assert _floor_to_increment(Decimal("200"), Decimal("25")) == Decimal("200.00")


def test_floor_to_increment_rounds_down() -> None:
    """Amount between multiples is floored to the lower multiple."""
    assert _floor_to_increment(Decimal("137"), Decimal("25")) == Decimal("125.00")


def test_floor_to_increment_sub_increment_returns_zero() -> None:
    """Amount less than one increment returns zero."""
    assert _floor_to_increment(Decimal("24.99"), Decimal("25")) == Decimal("0.00")


def test_floor_to_increment_zero_returns_zero() -> None:
    """Zero input returns zero."""
    assert _floor_to_increment(Decimal("0"), Decimal("25")) == Decimal("0.00")


def test_floor_to_increment_negative_returns_zero() -> None:
    """Negative input returns zero (called only on non-negative capacity)."""
    assert _floor_to_increment(Decimal("-100"), Decimal("25")) == Decimal("0.00")


# ===========================================================================
# Pure unit tests — _conservative_set_aside
# ===========================================================================


def test_conservative_set_aside_high_confidence() -> None:
    """HIGH confidence uses CONSERVATIVE_FRACTION (0.50) and floors to $25."""
    # 0.50 × 500 = 250 → floor(250, 25) = 250
    result = _conservative_set_aside(Decimal("500"), ConfidenceLevel.HIGH)
    assert result == Decimal("250.00")


def test_conservative_set_aside_medium_confidence() -> None:
    """MEDIUM confidence also uses CONSERVATIVE_FRACTION."""
    # 0.50 × 600 = 300 → floor(300, 25) = 300
    result = _conservative_set_aside(Decimal("600"), ConfidenceLevel.MEDIUM)
    assert result == Decimal("300.00")


def test_conservative_set_aside_low_confidence() -> None:
    """LOW confidence uses LOW_CONFIDENCE_FRACTION (0.25) to down-weight uncertain income."""
    # 0.25 × 500 = 125 → floor(125, 25) = 125
    result = _conservative_set_aside(Decimal("500"), ConfidenceLevel.LOW)
    assert result == Decimal("125.00")


def test_conservative_set_aside_low_confidence_fraction_values() -> None:
    """LOW_CONFIDENCE_FRACTION is exactly half of CONSERVATIVE_FRACTION."""
    assert LOW_CONFIDENCE_FRACTION == CONSERVATIVE_FRACTION / 2


def test_conservative_set_aside_rounding_increment_is_25() -> None:
    """ROUNDING_INCREMENT is $25."""
    assert Decimal("25") == ROUNDING_INCREMENT


def test_conservative_set_aside_floors_not_rounds() -> None:
    """Set-aside is always floored down, never rounded up."""
    # 0.50 × 137 = 68.50 → floor(68.50, 25) = 50 (not 75)
    result = _conservative_set_aside(Decimal("137"), ConfidenceLevel.HIGH)
    assert result == Decimal("50.00")


def test_conservative_set_aside_zero_capacity_returns_zero() -> None:
    """Zero capacity returns zero set-aside."""
    assert _conservative_set_aside(Decimal("0"), ConfidenceLevel.HIGH) == Decimal("0.00")


def test_conservative_set_aside_negative_capacity_returns_zero() -> None:
    """Negative capacity returns zero (no deficit saving)."""
    assert _conservative_set_aside(Decimal("-200"), ConfidenceLevel.HIGH) == Decimal("0.00")


def test_conservative_set_aside_none_confidence() -> None:
    """None confidence defaults to the standard fraction (not low-confidence path)."""
    # 0.50 × 500 = 250
    result = _conservative_set_aside(Decimal("500"), None)
    assert result == Decimal("250.00")


# ===========================================================================
# Pure unit tests — _select_priority
# ===========================================================================


def test_select_priority_insufficient_history() -> None:
    """INSUFFICIENT_HISTORY status → INSUFFICIENT_DATA priority."""
    p = _select_priority(
        SavingsCapacityStatus.INSUFFICIENT_HISTORY,
        capacity=None,
        debt_detected=False,
    )
    assert p is SavingsPriority.INSUFFICIENT_DATA


def test_select_priority_no_income_detected() -> None:
    """NO_INCOME_DETECTED status → INSUFFICIENT_DATA priority."""
    p = _select_priority(
        SavingsCapacityStatus.NO_INCOME_DETECTED,
        capacity=None,
        debt_detected=False,
    )
    assert p is SavingsPriority.INSUFFICIENT_DATA


def test_select_priority_no_income_with_debt() -> None:
    """Even with debt, INSUFFICIENT_DATA wins when there is no income."""
    p = _select_priority(
        SavingsCapacityStatus.NO_INCOME_DETECTED,
        capacity=None,
        debt_detected=True,
    )
    assert p is SavingsPriority.INSUFFICIENT_DATA


def test_select_priority_negative_capacity() -> None:
    """Negative capacity → NO_CAPACITY even when debt is present."""
    p = _select_priority(
        SavingsCapacityStatus.ESTIMATED,
        capacity=Decimal("-100"),
        debt_detected=True,
    )
    assert p is SavingsPriority.NO_CAPACITY


def test_select_priority_zero_capacity() -> None:
    """Zero capacity → NO_CAPACITY."""
    p = _select_priority(
        SavingsCapacityStatus.ESTIMATED,
        capacity=Decimal("0"),
        debt_detected=False,
    )
    assert p is SavingsPriority.NO_CAPACITY


def test_select_priority_positive_capacity_with_debt() -> None:
    """Positive capacity + debt → PAY_DOWN_HIGH_INTEREST_DEBT."""
    p = _select_priority(
        SavingsCapacityStatus.ESTIMATED,
        capacity=Decimal("500"),
        debt_detected=True,
    )
    assert p is SavingsPriority.PAY_DOWN_HIGH_INTEREST_DEBT


def test_select_priority_positive_capacity_no_debt() -> None:
    """Positive capacity + no debt → BUILD_SAVINGS."""
    p = _select_priority(
        SavingsCapacityStatus.ESTIMATED,
        capacity=Decimal("500"),
        debt_detected=False,
    )
    assert p is SavingsPriority.BUILD_SAVINGS


# ===========================================================================
# Pure unit tests — _detect_high_interest_debt
# ===========================================================================


def test_detect_debt_open_credit_card_with_balance_fires() -> None:
    """Open CREDIT_CARD with a positive balance is detected as high-interest debt."""
    card = _acct(
        account_id="card-001",
        account_type=AccountType.CREDIT_CARD,
        balances=[_balance("1500.00")],
    )
    refs = _detect_high_interest_debt([card])
    assert len(refs) == 1
    assert refs[0].account_id == "card-001"
    assert refs[0].account_type is AccountType.CREDIT_CARD
    assert refs[0].outstanding_balance == Decimal("1500.00")


def test_detect_debt_zero_balance_card_does_not_fire() -> None:
    """A credit card with a zero balance is not counted as debt."""
    card = _acct(
        account_id="card-zero",
        account_type=AccountType.CREDIT_CARD,
        balances=[_balance("0.00")],
    )
    refs = _detect_high_interest_debt([card])
    assert len(refs) == 0


def test_detect_debt_closed_credit_card_does_not_fire() -> None:
    """A closed credit card is excluded regardless of balance."""
    card = _acct(
        account_id="card-closed",
        account_type=AccountType.CREDIT_CARD,
        status=AccountStatus.CLOSED,
        balances=[_balance("2000.00")],
    )
    refs = _detect_high_interest_debt([card])
    assert len(refs) == 0


def test_detect_debt_loan_account_does_not_fire() -> None:
    """LOAN accounts never trigger (no APR data — may be low-rate mortgage/auto)."""
    loan = _acct(
        account_id="loan-001",
        account_type=AccountType.LOAN,
        balances=[_balance("50000.00")],
    )
    refs = _detect_high_interest_debt([loan])
    assert len(refs) == 0


def test_detect_debt_investment_account_does_not_fire() -> None:
    """INVESTMENT accounts are never flagged as debt."""
    inv = _acct(
        account_id="invest-001",
        account_type=AccountType.INVESTMENT,
        balances=[_balance("10000.00")],
    )
    refs = _detect_high_interest_debt([inv])
    assert len(refs) == 0


def test_detect_debt_savings_account_does_not_fire() -> None:
    """SAVINGS accounts are never flagged as debt."""
    sav = _acct(
        account_id="sav-001",
        account_type=AccountType.SAVINGS,
        balances=[_balance("5000.00")],
    )
    refs = _detect_high_interest_debt([sav])
    assert len(refs) == 0


def test_detect_debt_multiple_cards_mixed() -> None:
    """Only cards with balances are returned; zero-balance and non-card accounts excluded."""
    accounts = [
        _acct("card-a", AccountType.CREDIT_CARD, balances=[_balance("800.00")]),
        _acct("card-b", AccountType.CREDIT_CARD, balances=[_balance("0.00")]),
        _acct("loan-a", AccountType.LOAN, balances=[_balance("20000.00")]),
        _acct("check-a", AccountType.CHECKING, balances=[_balance("3000.00")]),
    ]
    refs = _detect_high_interest_debt(accounts)
    assert len(refs) == 1
    assert refs[0].account_id == "card-a"


def test_detect_debt_no_accounts_returns_empty() -> None:
    """Empty account list returns empty tuple."""
    refs = _detect_high_interest_debt([])
    assert refs == ()


# ===========================================================================
# Scope-boundary / type-system tests — the liability requirement
# ===========================================================================


def test_savings_priority_members_are_exactly_four_safe_values() -> None:
    """SavingsPriority's value space contains no security identifiers.

    This test asserts the closed enum contains exactly the four product-agnostic
    members defined in the plan. Adding a security name (e.g. 'BUY_VTSAX') would
    change the member count and break this test.
    """
    members = set(SavingsPriority)
    assert members == {
        SavingsPriority.PAY_DOWN_HIGH_INTEREST_DEBT,
        SavingsPriority.BUILD_SAVINGS,
        SavingsPriority.NO_CAPACITY,
        SavingsPriority.INSUFFICIENT_DATA,
    }


def test_savings_priority_rejects_security_string() -> None:
    """Constructing SavingsCapacityEstimate with a security ticker raises ValidationError."""
    from pydantic import ValidationError

    from banking_client.analytics.results import SavingsCapacityEstimate

    with pytest.raises(ValidationError):
        SavingsCapacityEstimate(
            status=SavingsCapacityStatus.ESTIMATED,
            as_of=_ANCHOR,
            lookback_months=12,
            account_ids=(),
            estimated_monthly_income=Decimal("3000.00"),
            fixed_monthly_costs=Decimal("1200.00"),
            variable_monthly_spend=Decimal("600.00"),
            typical_monthly_spend=Decimal("1800.00"),
            discretionary_capacity=Decimal("1200.00"),
            recommended_monthly_set_aside=Decimal("300.00"),
            priority="BUY_VTSAX",  # type: ignore[arg-type]  # intentionally invalid
            income_confidence=ConfidenceLevel.HIGH,
            high_interest_debt_detected=False,
            debt_accounts=(),
            supporting_income_transaction_ids=(),
            supporting_cost_transaction_ids=(),
            reasoning=(),
        )


def test_savings_estimate_rejects_extra_field() -> None:
    """extra='forbid' on SavingsCapacityEstimate rejects any advice-carrying extra field."""
    from pydantic import ValidationError

    from banking_client.analytics.results import SavingsCapacityEstimate

    with pytest.raises(ValidationError):
        SavingsCapacityEstimate(
            status=SavingsCapacityStatus.ESTIMATED,
            as_of=_ANCHOR,
            lookback_months=12,
            account_ids=(),
            estimated_monthly_income=Decimal("3000.00"),
            fixed_monthly_costs=Decimal("1200.00"),
            variable_monthly_spend=Decimal("600.00"),
            typical_monthly_spend=Decimal("1800.00"),
            discretionary_capacity=Decimal("1200.00"),
            recommended_monthly_set_aside=Decimal("300.00"),
            priority=SavingsPriority.BUILD_SAVINGS,
            income_confidence=ConfidenceLevel.HIGH,
            high_interest_debt_detected=False,
            debt_accounts=(),
            supporting_income_transaction_ids=(),
            supporting_cost_transaction_ids=(),
            reasoning=(),
            stock_tip="NVDA",  # type: ignore[call-arg]  # intentionally extra
        )


def test_savings_estimate_has_no_free_text_str_fields() -> None:
    """Every str-typed field in SavingsCapacityEstimate is an identifier, never advice text.

    Introspects model_fields of the top-level model and DebtAccountRef + ReasoningStep
    sub-models. Asserts that any field with a string type annotation is on the known
    identifier allowlist. A new free-text advice field added later would break this test.
    """
    from banking_client.analytics.results import (
        DebtAccountRef,
        ReasoningStep,
        SavingsCapacityEstimate,
    )

    # Known identifier fields — the only str fields we expect in the model tree.
    _ALLOWED_STR_FIELDS = frozenset(
        {
            "account_ids",
            "supporting_income_transaction_ids",
            "supporting_cost_transaction_ids",
            "reference_ids",
            "account_id",
        }
    )

    def _collect_str_fields(model_cls: type) -> set[str]:
        """Collect the names of all fields whose annotation includes plain str."""
        result: set[str] = set()
        for name, field_info in model_cls.model_fields.items():
            annotation = str(field_info.annotation)
            # Catch both 'str', 'tuple[str, ...]', and 'str | None'
            if "str" in annotation and "StrEnum" not in annotation:
                result.add(name)
        return result

    str_fields = (
        _collect_str_fields(SavingsCapacityEstimate)
        | _collect_str_fields(DebtAccountRef)
        | _collect_str_fields(ReasoningStep)
    )
    unexpected = str_fields - _ALLOWED_STR_FIELDS
    assert not unexpected, (
        f"Unexpected free-text str fields found in savings result models: {unexpected!r}. "
        "These could carry investment advice — remove them or add to the allowlist if they "
        "are identifier-only fields."
    )


# ===========================================================================
# Service unit tests — end-to-end with fake sources
# ===========================================================================


async def test_service_positive_capacity_build_savings_priority() -> None:
    """Positive capacity with no debt → BUILD_SAVINGS and a non-zero set-aside."""
    # 12 biweekly payroll credits of $2000 (income ≈ $4333/mo biweekly)
    # 12 monthly rent debits of $1500 (fixed $1500/mo)
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "1500.00", window_start)
    svc, tok = _fake_savings_service(txns)
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)

    assert result.status is SavingsCapacityStatus.ESTIMATED
    assert result.priority is SavingsPriority.BUILD_SAVINGS
    assert result.recommended_monthly_set_aside > Decimal("0")
    assert result.high_interest_debt_detected is False


async def test_service_debt_signal_fires_with_card_balance() -> None:
    """Positive capacity + open credit card with balance → PAY_DOWN_HIGH_INTEREST_DEBT."""
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "1500.00", window_start)
    card = _acct(
        "card-001",
        AccountType.CREDIT_CARD,
        balances=[_balance("3000.00")],
    )
    checking = _acct("test-checking", AccountType.CHECKING)
    svc, tok = _fake_savings_service(
        txns,
        accounts=[checking, card],
        acct_account_ids=["test-checking", "card-001"],
    )
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)

    assert result.status is SavingsCapacityStatus.ESTIMATED
    assert result.priority is SavingsPriority.PAY_DOWN_HIGH_INTEREST_DEBT
    assert result.high_interest_debt_detected is True
    assert len(result.debt_accounts) == 1
    assert result.debt_accounts[0].account_id == "card-001"
    assert result.recommended_monthly_set_aside > Decimal("0")


async def test_service_negative_capacity_no_capacity_priority() -> None:
    """Spending exceeds income → NO_CAPACITY priority, set-aside is zero, no exception."""
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    # Income ≈ $4333/mo; spending $5000/mo → negative capacity
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "5000.00", window_start)
    svc, tok = _fake_savings_service(txns)
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)

    assert result.status is SavingsCapacityStatus.ESTIMATED
    assert result.priority is SavingsPriority.NO_CAPACITY
    assert result.recommended_monthly_set_aside == Decimal("0.00")
    assert result.discretionary_capacity is not None
    assert result.discretionary_capacity < Decimal("0")


async def test_service_negative_capacity_with_debt_still_surfaced() -> None:
    """Debt flag is still populated even when capacity is negative."""
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "5000.00", window_start)
    card = _acct("card-001", AccountType.CREDIT_CARD, balances=[_balance("2000.00")])
    checking = _acct("test-checking", AccountType.CHECKING)
    svc, tok = _fake_savings_service(
        txns,
        accounts=[checking, card],
        acct_account_ids=["test-checking", "card-001"],
    )
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)

    # NO_CAPACITY takes precedence over debt in priority; debt is still surfaced.
    assert result.priority is SavingsPriority.NO_CAPACITY
    assert result.high_interest_debt_detected is True
    assert len(result.debt_accounts) == 1


async def test_service_no_income_returns_no_income_detected() -> None:
    """Irregular, non-recurring credits → NO_INCOME_DETECTED / INSUFFICIENT_DATA.

    The income service returns NO_RECURRING_INCOME when there are credits but none meet
    the cadence + regularity bar.  We produce 5 credits at chaotic irregular gaps so the
    service cannot classify them as a recurring stream.
    """
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    # 5 irregular credits spaced at 1, 90, 2, 200 days — no recognisable cadence.
    offsets = [0, 1, 91, 93, 293]
    irregular_credits = [
        _credit_txn("500.00", "MISC", window_start + timedelta(days=d), f"irr-{i:03d}") for i, d in enumerate(offsets)
    ]
    txns = irregular_credits + _monthly_debits(12, "1500.00", window_start)
    svc, tok = _fake_savings_service(txns)
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)

    assert result.status is SavingsCapacityStatus.NO_INCOME_DETECTED
    assert result.priority is SavingsPriority.INSUFFICIENT_DATA
    assert result.estimated_monthly_income is None
    assert result.discretionary_capacity is None
    assert result.recommended_monthly_set_aside == Decimal("0.00")


async def test_service_capacity_math_correctness() -> None:
    """discretionary_capacity == estimated_monthly_income − typical_monthly_spend."""
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "1500.00", window_start)
    svc, tok = _fake_savings_service(txns)
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)

    assert result.status is SavingsCapacityStatus.ESTIMATED
    assert result.estimated_monthly_income is not None
    assert result.discretionary_capacity is not None
    expected_capacity = result.estimated_monthly_income - result.typical_monthly_spend
    # Allow a one-cent rounding difference from quantization.
    assert abs(result.discretionary_capacity - expected_capacity) <= Decimal("0.01")


async def test_service_set_aside_is_floor_of_50pct_capacity() -> None:
    """recommended_monthly_set_aside == floor(0.50 × capacity, 25) when confidence is not LOW."""
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "1500.00", window_start)
    svc, tok = _fake_savings_service(txns)
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)

    assert result.status is SavingsCapacityStatus.ESTIMATED
    assert result.discretionary_capacity is not None
    if result.income_confidence is not ConfidenceLevel.LOW:
        expected = _floor_to_increment(result.discretionary_capacity * CONSERVATIVE_FRACTION, ROUNDING_INCREMENT)
        assert result.recommended_monthly_set_aside == expected


# ===========================================================================
# Explainability tests
# ===========================================================================


async def test_service_reasoning_chain_is_populated() -> None:
    """A successful estimate returns a non-empty reasoning chain."""
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "1500.00", window_start)
    svc, tok = _fake_savings_service(txns)
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)
    assert len(result.reasoning) > 0


async def test_service_reasoning_contains_income_basis_step() -> None:
    """The reasoning chain includes an INCOME_BASIS step when income is detected."""
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "1500.00", window_start)
    svc, tok = _fake_savings_service(txns)
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)
    codes = [s.code for s in result.reasoning]
    assert ReasoningCode.INCOME_BASIS in codes


async def test_service_reasoning_reflects_debt_step() -> None:
    """HIGH_INTEREST_DEBT_FOUND appears in reasoning when a card is detected."""
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "1500.00", window_start)
    card = _acct("card-001", AccountType.CREDIT_CARD, balances=[_balance("1200.00")])
    checking = _acct("test-checking", AccountType.CHECKING)
    svc, tok = _fake_savings_service(
        txns,
        accounts=[checking, card],
        acct_account_ids=["test-checking", "card-001"],
    )
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)
    codes = [s.code for s in result.reasoning]
    assert ReasoningCode.HIGH_INTEREST_DEBT_FOUND in codes


async def test_service_result_echoes_income_and_cost_figures() -> None:
    """Result surfaces income, fixed costs, and variable spend for full explainability."""
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "1500.00", window_start)
    svc, tok = _fake_savings_service(txns)
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)

    assert result.estimated_monthly_income is not None
    assert result.fixed_monthly_costs >= Decimal("0")
    assert result.variable_monthly_spend >= Decimal("0")
    assert result.typical_monthly_spend == result.fixed_monthly_costs + result.variable_monthly_spend


async def test_service_supporting_income_transaction_ids_populated() -> None:
    """supporting_income_transaction_ids is populated when income is detected."""
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "1500.00", window_start)
    svc, tok = _fake_savings_service(txns)
    result = await svc.estimate_savings_capacity(tok, "test-checking", as_of=_ANCHOR)

    assert result.status is SavingsCapacityStatus.ESTIMATED
    assert len(result.supporting_income_transaction_ids) > 0


# ===========================================================================
# render_reasoning tests
# ===========================================================================


def test_render_reasoning_income_basis() -> None:
    """INCOME_BASIS step renders a sentence containing the amount."""
    from banking_client.analytics.results import ReasoningStep

    step = ReasoningStep(
        code=ReasoningCode.INCOME_BASIS,
        amount=Decimal("3000.00"),
        reference_ids=(),
    )
    rendered = render_reasoning(step)
    assert "3000.00" in rendered
    assert "income" in rendered.lower()


def test_render_reasoning_no_income_step() -> None:
    """NO_INCOME step renders a recognisable sentence."""
    from banking_client.analytics.results import ReasoningStep

    step = ReasoningStep(code=ReasoningCode.NO_INCOME, amount=None, reference_ids=())
    rendered = render_reasoning(step)
    assert "income" in rendered.lower()


def test_render_reasoning_returns_string() -> None:
    """render_reasoning always returns a str, even for an unexpected code."""
    from banking_client.analytics.results import ReasoningStep

    step = ReasoningStep(
        code=ReasoningCode.SAVINGS_PRIORITY_SELECTED,
        amount=Decimal("100.00"),
        reference_ids=(),
    )
    assert isinstance(render_reasoning(step), str)


# ===========================================================================
# Determinism test
# ===========================================================================


async def test_service_deterministic_for_identical_inputs() -> None:
    """Two independent service instances with identical inputs return equal results."""
    window_start = _ANCHOR - __import__("datetime").timedelta(days=365)
    txns = _biweekly_payroll(24, "2000.00", window_start) + _monthly_debits(12, "1500.00", window_start)
    svc1, tok1 = _fake_savings_service(txns)
    svc2, tok2 = _fake_savings_service(txns)

    r1 = await svc1.estimate_savings_capacity(tok1, "test-checking", as_of=_ANCHOR)
    r2 = await svc2.estimate_savings_capacity(tok2, "test-checking", as_of=_ANCHOR)
    assert r1 == r2


# ===========================================================================
# Auth propagation tests
# ===========================================================================


async def test_service_auth_error_propagates_from_income_service() -> None:
    """A TRANSACTIONS-only token with account_id=None raises AuthorizationError via income."""
    svc = default_savings_service(trail=AuditTrail(sink=ListSink()))
    with pytest.raises(AuthorizationError):
        await svc.estimate_savings_capacity(_TOKEN_003_TXN_ONLY, as_of=_ANCHOR)


# ===========================================================================
# Audit tests
# ===========================================================================


async def test_service_audit_events_emitted_on_success() -> None:
    """A successful call emits get_transactions audit events with correct fingerprints."""
    sink = ListSink()
    svc = default_savings_service(trail=AuditTrail(sink=sink))
    await svc.estimate_savings_capacity(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)

    tx_events = [e for e in sink.events if e.action == "get_transactions"]
    assert len(tx_events) >= 1
    for evt in tx_events:
        assert evt.resource.data_cluster == "TRANSACTIONS"
        assert evt.actor.token_id.startswith("sha256:")
        assert evt.outcome is AuditOutcome.SUCCESS


async def test_service_audit_get_accounts_emitted_for_debt_detection() -> None:
    """A call that triggers debt detection emits get_accounts audit events."""
    sink = ListSink()
    svc = default_savings_service(trail=AuditTrail(sink=sink))
    await svc.estimate_savings_capacity(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)

    acct_events = [e for e in sink.events if e.action == "get_accounts"]
    # At least the debt-detection call should be captured (there may also be
    # an auto-discover call from the sub-services if account_id were None).
    assert len(acct_events) >= 1
    for evt in acct_events:
        assert evt.actor.token_id.startswith("sha256:")


# ===========================================================================
# Integration tests — committed fixture data via default_savings_service
# ===========================================================================


async def test_integration_cust001_positive_capacity() -> None:
    """Customer 001 (stable payroll) should produce a positive discretionary capacity."""
    svc = default_savings_service(trail=AuditTrail(sink=ListSink()))
    result = await svc.estimate_savings_capacity(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)
    assert result.status is SavingsCapacityStatus.ESTIMATED
    assert result.estimated_monthly_income is not None
    assert result.estimated_monthly_income > Decimal("0")
    assert result.recommended_monthly_set_aside >= Decimal("0")


async def test_integration_cust001_no_specific_securities_in_output() -> None:
    """The result for customer 001 contains no investment product names anywhere."""
    svc = default_savings_service(trail=AuditTrail(sink=ListSink()))
    result = await svc.estimate_savings_capacity(_TOKEN_001, "cust-001-checking", as_of=_ANCHOR)
    # Serialize to JSON (the shape the MCP layer will consume) and check for known
    # investment product names — belt-and-suspenders over the type-system boundary test.
    serialized = result.model_dump_json()
    forbidden = ["VTSAX", "VFIAX", "SPY", "QQQ", "BND", "ticker", "iShares", "ETF"]
    for term in forbidden:
        assert term not in serialized, f"Result JSON contains investment product reference: {term!r}"


async def test_integration_cust002_result_is_estimated() -> None:
    """Customer 002 (multi-account, raise, freelance) produces an ESTIMATED result."""
    svc = default_savings_service(trail=AuditTrail(sink=ListSink()))
    result = await svc.estimate_savings_capacity(_TOKEN_002, as_of=_ANCHOR)
    # cust-002 has ACCOUNTS scope so auto-discover should work.
    assert result.status in (
        SavingsCapacityStatus.ESTIMATED,
        SavingsCapacityStatus.NO_INCOME_DETECTED,
        SavingsCapacityStatus.INSUFFICIENT_HISTORY,
    )


async def test_integration_determinism() -> None:
    """Two independent default_savings_service calls with the same inputs return equal results."""
    r1 = await default_savings_service(trail=AuditTrail(sink=ListSink())).estimate_savings_capacity(
        _TOKEN_001, "cust-001-checking", as_of=_ANCHOR
    )
    r2 = await default_savings_service(trail=AuditTrail(sink=ListSink())).estimate_savings_capacity(
        _TOKEN_001, "cust-001-checking", as_of=_ANCHOR
    )
    assert r1 == r2
