"""Deterministic savings-capacity service.

This module answers the capstone's headline question: *how much can this customer
realistically set aside each month, and what should they do first?*

Architecture — composition, not re-pull
-----------------------------------------
:class:`SavingsCapacityService` **composes** :class:`~banking_client.analytics.income.IncomeService`
and :class:`~banking_client.analytics.spending.SpendingService`.  It never pulls raw
transactions itself.  Auth, audit, and 1033 data minimization are fully inherited from
the two sub-services and their underlying clients.

The only new raw read this service performs is a single, minimal account-metadata fetch
(account type + balance only, through the already-audited :class:`AccountsClient`) to
detect revolving credit-card debt.  No card *transactions* are ever pulled.

Capacity calculation
---------------------
::

    capacity = estimated_monthly_income − fixed_monthly_costs − variable_monthly_spend

``typical_monthly_spend`` (= fixed + variable) already excludes self-transfers and
statistical outliers, so capacity is conservative before any haircut.

The recommended set-aside is:

::

    fraction  = LOW_CONFIDENCE_FRACTION (0.25) if income confidence is LOW
                else CONSERVATIVE_FRACTION (0.50)
    set_aside = floor_to_increment(capacity × fraction, ROUNDING_INCREMENT=$25)
    set_aside = max(set_aside, 0)

No-advice boundary
-------------------
This service deliberately cannot recommend specific securities, indices, funds, or
tickers — doing so would constitute licensed financial advice.  The boundary is enforced
*structurally* by the :class:`~banking_client.analytics.results.SavingsCapacityEstimate`
return type:

1. The only recommendation field is ``priority: SavingsPriority``, a closed ``StrEnum``
   whose four members contain no security identifiers.
2. There is no free-text advice field anywhere in the model (the reasoning chain is
   enum-coded via :class:`~banking_client.analytics.results.ReasoningCode`).
3. ``extra="forbid"`` on the top-level model rejects any extra field at construction time.

Human-readable prose is produced by the :func:`render_reasoning` helper in *this* module
(outside the type), so the model itself is permanently advice-free.

Determinism guarantee
----------------------
Given identical inputs the service always returns an identical
:class:`~banking_client.analytics.results.SavingsCapacityEstimate`.  The ``as_of``
timestamp is resolved **once** and passed to both sub-services so income and spending
share an identical lookback window.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Final

from banking_client.analytics.income import IncomeService, default_income_service
from banking_client.analytics.results import (
    CONSERVATIVE_FRACTION,
    LOW_CONFIDENCE_FRACTION,
    ROUNDING_INCREMENT,
    ConfidenceLevel,
    DebtAccountRef,
    IncomeStatus,
    ReasoningCode,
    ReasoningStep,
    SavingsCapacityEstimate,
    SavingsCapacityStatus,
    SavingsPriority,
    SpendingStatus,
)
from banking_client.analytics.spending import SpendingService, default_spending_service
from banking_client.client.accounts import AccountsClient, default_accounts_client
from banking_client.models.account import Account
from banking_client.models.enums import AccountStatus, AccountType, BalanceType
from common.audit import AuditTrail

_ZERO: Final[Decimal] = Decimal("0.00")


def _q(amount: Decimal) -> Decimal:
    """Quantize *amount* to two decimal places using ROUND_HALF_UP."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Pure helpers — unit-tested in isolation
# ---------------------------------------------------------------------------


def _outstanding_balance(account: Account) -> Decimal:
    """Return the CURRENT balance for *account* as an absolute (positive) Decimal.

    Prefers the CURRENT balance (posted ledger); falls back to the first available
    balance if CURRENT is not present.  Returns zero when no balances are reported.

    Args:
        account: The account whose balance to read.

    Returns:
        Absolute value of the balance, quantized to two decimal places.
    """
    current = next(
        (b for b in account.balances if b.balance_type is BalanceType.CURRENT),
        None,
    )
    if current is None:
        current = account.balances[0] if account.balances else None
    if current is None:
        return _ZERO
    return _q(abs(current.amount.value))


def _detect_high_interest_debt(accounts: list[Account]) -> tuple[DebtAccountRef, ...]:
    """Identify OPEN CREDIT_CARD accounts carrying a revolving balance.

    Only CREDIT_CARD accounts are considered — LOAN and INVESTMENT accounts are excluded
    because no APR data is available from the FDX Account model.  Assuming a low-rate
    mortgage is high-interest debt would produce incorrect guidance.

    Args:
        accounts: Accounts to scan (typically all accounts for the customer).

    Returns:
        Tuple of :class:`~banking_client.analytics.results.DebtAccountRef` evidence
        records, one per card with an outstanding balance.  Empty tuple when no such
        accounts are found.
    """
    refs: list[DebtAccountRef] = []
    for acct in accounts:
        if acct.account_type is not AccountType.CREDIT_CARD:
            continue
        if acct.status is not AccountStatus.OPEN:
            continue
        balance = _outstanding_balance(acct)
        if balance > _ZERO:
            refs.append(
                DebtAccountRef(
                    account_id=acct.id,
                    account_type=acct.account_type,
                    outstanding_balance=balance,
                )
            )
    return tuple(refs)


def _compute_capacity(
    income: Decimal,
    fixed: Decimal,
    variable: Decimal,
) -> Decimal:
    """Compute discretionary capacity = income − fixed − variable.

    Args:
        income: Estimated monthly income.
        fixed: Fixed monthly costs from the spending analysis.
        variable: Typical variable monthly spend (outliers excluded upstream).

    Returns:
        Discretionary capacity, quantized to two decimal places.  May be negative.
    """
    return _q(income - fixed - variable)


def _floor_to_increment(amount: Decimal, increment: Decimal) -> Decimal:
    """Floor *amount* down to the nearest multiple of *increment*.

    Uses ``ROUND_DOWN`` so the result is always ≤ *amount* — never over-promising.
    Returns zero when *amount* is less than one full *increment*.

    Args:
        amount: The raw figure to round.
        increment: The rounding step (e.g. ``Decimal("25")``).

    Returns:
        The floored multiple, quantized to two decimal places.
    """
    if amount <= _ZERO or increment <= _ZERO:
        return _ZERO
    # Divide, floor to integer multiples, multiply back.
    multiples = (amount / increment).to_integral_value(rounding=ROUND_DOWN)
    return _q(multiples * increment)


def _conservative_set_aside(
    capacity: Decimal,
    confidence: ConfidenceLevel | None,
) -> Decimal:
    """Apply the conservative haircut to produce the recommended monthly set-aside.

    Uses ``LOW_CONFIDENCE_FRACTION`` (0.25) when income confidence is LOW to account
    for income uncertainty; uses ``CONSERVATIVE_FRACTION`` (0.50) otherwise.

    Args:
        capacity: Discretionary capacity (may be negative or zero).
        confidence: Income confidence band from the income service.

    Returns:
        Recommended set-aside, floored to ``ROUNDING_INCREMENT`` ($25).  Always ≥ 0.
    """
    if capacity <= _ZERO:
        return _ZERO
    fraction = LOW_CONFIDENCE_FRACTION if confidence is ConfidenceLevel.LOW else CONSERVATIVE_FRACTION
    raw = _q(capacity * fraction)
    return _floor_to_increment(raw, ROUNDING_INCREMENT)


def _select_priority(
    status: SavingsCapacityStatus,
    capacity: Decimal | None,
    debt_detected: bool,
) -> SavingsPriority:
    """Choose the product-agnostic priority signal from the computed state.

    Precedence (highest to lowest):
    1. Insufficient data → INSUFFICIENT_DATA.
    2. No income detected → INSUFFICIENT_DATA.
    3. Negative/zero capacity → NO_CAPACITY (debt flag still surfaced separately).
    4. Positive capacity + debt → PAY_DOWN_HIGH_INTEREST_DEBT.
    5. Positive capacity + no debt → BUILD_SAVINGS.

    Args:
        status: Top-level capacity status.
        capacity: Computed discretionary capacity, or ``None``.
        debt_detected: Whether high-interest credit-card debt was found.

    Returns:
        The appropriate :class:`~banking_client.analytics.results.SavingsPriority`.
    """
    if status in (
        SavingsCapacityStatus.INSUFFICIENT_HISTORY,
        SavingsCapacityStatus.NO_INCOME_DETECTED,
    ):
        return SavingsPriority.INSUFFICIENT_DATA
    if capacity is None or capacity <= _ZERO:
        return SavingsPriority.NO_CAPACITY
    if debt_detected:
        return SavingsPriority.PAY_DOWN_HIGH_INTEREST_DEBT
    return SavingsPriority.BUILD_SAVINGS


def _build_reasoning(
    *,
    status: SavingsCapacityStatus,
    income: Decimal | None,
    fixed: Decimal,
    variable: Decimal,
    capacity: Decimal | None,
    set_aside: Decimal,
    confidence: ConfidenceLevel | None,
    debt_accounts: tuple[DebtAccountRef, ...],
    priority: SavingsPriority,
    income_tx_ids: tuple[str, ...],
    cost_tx_ids: tuple[str, ...],
) -> tuple[ReasoningStep, ...]:
    """Build the ordered reasoning chain for a capacity estimate.

    Each step corresponds to one arithmetic or logical operation.  The chain is enum-
    coded so the result model never carries free text — human-readable prose is produced
    by :func:`render_reasoning`.

    Args:
        status: Top-level capacity status.
        income: Estimated monthly income (None if unknown).
        fixed: Fixed monthly costs.
        variable: Variable monthly spend (outliers excluded).
        capacity: Computed discretionary capacity (None if unknown).
        set_aside: Recommended monthly set-aside.
        confidence: Income confidence band.
        debt_accounts: Detected high-interest-debt accounts.
        priority: Selected priority signal.
        income_tx_ids: Transaction ids grounding the income figure.
        cost_tx_ids: Transaction ids grounding the cost figures.

    Returns:
        Ordered tuple of :class:`~banking_client.analytics.results.ReasoningStep`.
    """
    steps: list[ReasoningStep] = []

    if status is SavingsCapacityStatus.INSUFFICIENT_HISTORY:
        steps.append(
            ReasoningStep(
                code=ReasoningCode.INSUFFICIENT_HISTORY,
                amount=None,
                reference_ids=(),
            )
        )
        return tuple(steps)

    if status is SavingsCapacityStatus.NO_INCOME_DETECTED:
        steps.append(ReasoningStep(code=ReasoningCode.NO_INCOME, amount=None, reference_ids=()))
        return tuple(steps)

    # ESTIMATED path — walk through the arithmetic.
    steps.append(
        ReasoningStep(
            code=ReasoningCode.INCOME_BASIS,
            amount=income,
            reference_ids=income_tx_ids[:10],  # cap at 10 ids for compactness
        )
    )
    steps.append(
        ReasoningStep(
            code=ReasoningCode.FIXED_COSTS_BASIS,
            amount=fixed,
            reference_ids=cost_tx_ids[:10],
        )
    )
    steps.append(
        ReasoningStep(
            code=ReasoningCode.VARIABLE_SPEND_BASIS,
            amount=variable,
            reference_ids=(),
        )
    )

    if capacity is not None and capacity <= _ZERO:
        steps.append(
            ReasoningStep(
                code=ReasoningCode.NEGATIVE_CAPACITY,
                amount=capacity,
                reference_ids=(),
            )
        )
    else:
        steps.append(
            ReasoningStep(
                code=ReasoningCode.CAPACITY_COMPUTED,
                amount=capacity,
                reference_ids=(),
            )
        )
        steps.append(
            ReasoningStep(
                code=ReasoningCode.CONSERVATIVE_HAIRCUT_APPLIED,
                amount=set_aside,
                reference_ids=(),
            )
        )

    if debt_accounts:
        steps.append(
            ReasoningStep(
                code=ReasoningCode.HIGH_INTEREST_DEBT_FOUND,
                amount=sum((d.outstanding_balance for d in debt_accounts), _ZERO),
                reference_ids=tuple(d.account_id for d in debt_accounts),
            )
        )

    if priority is SavingsPriority.PAY_DOWN_HIGH_INTEREST_DEBT:
        steps.append(
            ReasoningStep(
                code=ReasoningCode.DEBT_PRIORITY_SELECTED,
                amount=None,
                reference_ids=tuple(d.account_id for d in debt_accounts),
            )
        )
    elif priority is SavingsPriority.BUILD_SAVINGS:
        steps.append(
            ReasoningStep(
                code=ReasoningCode.SAVINGS_PRIORITY_SELECTED,
                amount=set_aside,
                reference_ids=(),
            )
        )

    return tuple(steps)


# ---------------------------------------------------------------------------
# Rendering — human-readable prose keyed on ReasoningCode
# (lives outside the type so the result model never carries free text)
# ---------------------------------------------------------------------------

_REASONING_TEMPLATES: Final[dict[ReasoningCode, str]] = {
    ReasoningCode.INCOME_BASIS: "Estimated monthly income: ${amount}",
    ReasoningCode.FIXED_COSTS_BASIS: "Fixed monthly costs deducted: ${amount}",
    ReasoningCode.VARIABLE_SPEND_BASIS: "Typical variable spend deducted (outliers excluded): ${amount}",
    ReasoningCode.CAPACITY_COMPUTED: "Discretionary capacity (income − costs): ${amount}",
    ReasoningCode.CONSERVATIVE_HAIRCUT_APPLIED: "Conservative set-aside after 50% haircut and $25 floor: ${amount}",
    ReasoningCode.NEGATIVE_CAPACITY: "Spending meets or exceeds income (capacity: ${amount}); no surplus to set aside.",
    ReasoningCode.NO_INCOME: "No recurring income detected; cannot estimate savings capacity.",
    ReasoningCode.INSUFFICIENT_HISTORY: "Insufficient transaction history; cannot estimate savings capacity.",
    ReasoningCode.HIGH_INTEREST_DEBT_FOUND: (
        "Open credit-card account(s) with revolving balance detected (total: ${amount})."
    ),
    ReasoningCode.DEBT_PRIORITY_SELECTED: "Paying down high-interest debt first is the boring-but-correct move.",
    ReasoningCode.SAVINGS_PRIORITY_SELECTED: "Positive surplus available — start building savings.",
}


def render_reasoning(step: ReasoningStep) -> str:
    """Produce a human-readable sentence for one reasoning step.

    This function lives *outside* :class:`~banking_client.analytics.results.SavingsCapacityEstimate`
    deliberately — keeping text generation outside the type ensures the model itself can
    never carry investment advice or free-form strings.

    Args:
        step: A single step from
            :attr:`~banking_client.analytics.results.SavingsCapacityEstimate.reasoning`.

    Returns:
        A short English sentence describing the step.
    """
    template = _REASONING_TEMPLATES.get(step.code, str(step.code))
    amount_str = str(step.amount) if step.amount is not None else "N/A"
    return template.replace("${amount}", amount_str)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SavingsCapacityService:
    """Deterministic savings-capacity service.

    Combines the income-determination and spending-analysis services into a single,
    conservative recommendation: how much the customer can realistically set aside per
    month, and whether paying down high-interest debt should come first.

    This service delegates all transaction data access to the injected
    :class:`~banking_client.analytics.income.IncomeService` and
    :class:`~banking_client.analytics.spending.SpendingService` — it never pulls raw
    transactions itself.  The only direct client call is a one-shot account listing for
    debt detection (account type + balance only).

    Args:
        income_service: Pre-configured income service (handles its own auth + audit).
        spending_service: Pre-configured spending service (handles its own auth + audit).
        accounts_client: Optional account client for credit-card debt detection.  When
            ``None``, debt detection is skipped and ``high_interest_debt_detected`` is
            always ``False``.

    Example::

        svc = default_savings_service()
        result = await svc.estimate_savings_capacity(
            "tok_cust_001", as_of=datetime(2026, 6, 30, tzinfo=UTC)
        )
        print(result.priority, result.recommended_monthly_set_aside)
    """

    def __init__(
        self,
        income_service: IncomeService,
        spending_service: SpendingService,
        accounts_client: AccountsClient | None = None,
    ) -> None:
        """Store the injected services and optional accounts client.

        Args:
            income_service: Income service with auth + audit.
            spending_service: Spending service with auth + audit.
            accounts_client: Account client for debt detection; may be ``None``.
        """
        self._income = income_service
        self._spending = spending_service
        self._acct_client = accounts_client

    async def estimate_savings_capacity(
        self,
        token: str,
        account_id: str | None = None,
        *,
        lookback_months: int = 12,
        as_of: datetime | None = None,
    ) -> SavingsCapacityEstimate:
        """Estimate how much the customer can realistically save per month.

        Pipeline:

        1. **Resolve the anchor date** — once, so both sub-services share an identical
           lookback window (determinism).
        2. **Income** — delegate to :meth:`~banking_client.analytics.income.IncomeService.estimate_regular_income`.
        3. **Spending** — delegate to :meth:`~banking_client.analytics.spending.SpendingService.analyze_spending`.
        4. **Debt detection** — if an :class:`AccountsClient` was injected, list all
           accounts and identify OPEN CREDIT_CARD accounts with a revolving balance.
        5. **Capacity math** — compute capacity, apply the conservative haircut, select
           the priority signal, and build the reasoning chain.
        6. **Assemble** the :class:`~banking_client.analytics.results.SavingsCapacityEstimate`.

        Args:
            token: Opaque bearer token passed to every underlying service/client call.
            account_id: Specific checking account to analyse.  When ``None`` both sub-
                services discover checking accounts automatically (requires ACCOUNTS scope).
            lookback_months: Months of history to analyse.  Default is 12.
            as_of: Upper bound of the lookback window; defaults to ``datetime.now(UTC)``.
                Inject a fixed datetime in tests for determinism.

        Returns:
            A :class:`~banking_client.analytics.results.SavingsCapacityEstimate`.

        Raises:
            AuthenticationError: Token unknown or expired (propagated from sub-services).
            AuthorizationError: Token lacks required scope (propagated from sub-services).
            ValueError: Neither sub-service has an accounts client and ``account_id`` is
                ``None`` (propagated from the sub-service that raises it first).
        """
        effective_as_of = as_of if as_of is not None else datetime.now(UTC)

        # ------------------------------------------------------------------
        # 1 + 2 + 3. Run income and spending (auth/audit/minimization delegated).
        # ------------------------------------------------------------------
        income_result = await self._income.estimate_regular_income(
            token,
            account_id,
            lookback_months=lookback_months,
            as_of=effective_as_of,
        )
        spending_result = await self._spending.analyze_spending(
            token,
            account_id,
            lookback_months=lookback_months,
            as_of=effective_as_of,
        )

        # ------------------------------------------------------------------
        # 4. Debt detection (one account listing; no transaction pull).
        # ------------------------------------------------------------------
        debt_accounts: tuple[DebtAccountRef, ...] = ()
        if self._acct_client is not None:
            accts_page = await self._acct_client.get_accounts(token, limit=100)
            debt_accounts = _detect_high_interest_debt(list(accts_page.items))
        high_interest_debt_detected = bool(debt_accounts)

        # ------------------------------------------------------------------
        # 5. Capacity math.
        # ------------------------------------------------------------------
        # Unified account ids: sorted union of both sub-results.
        account_ids: tuple[str, ...] = tuple(sorted(set(income_result.account_ids) | set(spending_result.account_ids)))

        # Determine overall status.
        income_insufficient = income_result.status.value == "INSUFFICIENT_HISTORY"
        spending_insufficient = spending_result.status is SpendingStatus.INSUFFICIENT_HISTORY
        no_income = income_result.status is IncomeStatus.NO_RECURRING_INCOME

        if income_insufficient or spending_insufficient:
            status = SavingsCapacityStatus.INSUFFICIENT_HISTORY
        elif income_result.estimated_monthly_income is None:
            # Covers INSUFFICIENT_HISTORY on income side (Decimal | None sentinel)
            # and NO_RECURRING_INCOME where estimated_monthly_income is None.
            status = SavingsCapacityStatus.NO_INCOME_DETECTED
        elif no_income:
            status = SavingsCapacityStatus.NO_INCOME_DETECTED
        else:
            status = SavingsCapacityStatus.ESTIMATED

        # Extract figures (defaults to zero when status is not ESTIMATED).
        income: Decimal | None = income_result.estimated_monthly_income
        fixed = spending_result.fixed_monthly_total
        variable = spending_result.variable_monthly_total
        typical = spending_result.typical_monthly_spend
        confidence = income_result.primary_source.confidence if income_result.primary_source is not None else None

        capacity: Decimal | None
        set_aside: Decimal
        if status is SavingsCapacityStatus.ESTIMATED and income is not None:
            capacity = _compute_capacity(income, fixed, variable)
            set_aside = _conservative_set_aside(capacity, confidence)
        else:
            capacity = None
            set_aside = _ZERO

        priority = _select_priority(status, capacity, high_interest_debt_detected)

        # Supporting transaction ids for explainability.
        income_tx_ids: tuple[str, ...] = (
            income_result.primary_source.supporting_transaction_ids if income_result.primary_source is not None else ()
        )
        cost_tx_ids: tuple[str, ...] = tuple(
            tid for rc in spending_result.recurring_costs for tid in rc.supporting_transaction_ids
        )

        reasoning = _build_reasoning(
            status=status,
            income=income,
            fixed=fixed,
            variable=variable,
            capacity=capacity,
            set_aside=set_aside,
            confidence=confidence,
            debt_accounts=debt_accounts,
            priority=priority,
            income_tx_ids=income_tx_ids,
            cost_tx_ids=cost_tx_ids,
        )

        # ------------------------------------------------------------------
        # 6. Assemble and return.
        # ------------------------------------------------------------------
        return SavingsCapacityEstimate(
            status=status,
            as_of=effective_as_of,
            lookback_months=lookback_months,
            account_ids=account_ids,
            estimated_monthly_income=income,
            fixed_monthly_costs=fixed,
            variable_monthly_spend=variable,
            typical_monthly_spend=typical,
            discretionary_capacity=capacity,
            recommended_monthly_set_aside=set_aside,
            priority=priority,
            income_confidence=confidence,
            high_interest_debt_detected=high_interest_debt_detected,
            debt_accounts=debt_accounts,
            supporting_income_transaction_ids=income_tx_ids,
            supporting_cost_transaction_ids=cost_tx_ids,
            reasoning=reasoning,
        )


def default_savings_service(*, trail: AuditTrail | None = None) -> SavingsCapacityService:
    """Return a :class:`SavingsCapacityService` wired to the committed fixture data.

    All three underlying clients (income, spending, accounts) share a **single audit
    trail** so one logical request's events land in one sink — important for tests and
    for the MCP layer that will later consume this service.

    Args:
        trail: Optional audit trail override.  Pass ``AuditTrail(sink=ListSink())`` in
            tests to avoid stdout noise and enable event assertions.

    Returns:
        A fully wired :class:`SavingsCapacityService` ready for async use.

    Example::

        svc = default_savings_service()
        result = await svc.estimate_savings_capacity("tok_cust_001")
    """
    return SavingsCapacityService(
        income_service=default_income_service(trail=trail),
        spending_service=default_spending_service(trail=trail),
        accounts_client=default_accounts_client(trail=trail),
    )
