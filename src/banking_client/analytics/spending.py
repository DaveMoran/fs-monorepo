"""Deterministic spending-analysis service.

This module analyses a customer's POSTED debit activity from FDX transaction history using the
minimum set of transaction fields mandated by the 1033 data-minimization principle.

1033 data-minimization contract
---------------------------------
Unlike the income service (which never reads ``tx.category``), spending analysis legitimately
uses ``category`` as the primary aggregation key — it is the only additional field beyond those
the income service consumes.

The service reads **exactly six** transaction fields:

- ``tx.id`` — read-only identifier for explainability output (never used in inference).
- ``tx.amount.value`` — the posted amount.
- ``tx.posted_timestamp`` — when the transaction settled; the cadence clock runs on this.
- ``tx.debit_credit_memo`` — direction; DEBITs are spend, REFUND-category CREDITs are netted.
- ``tx.payee`` — the normalized counterparty name used for recurring-cost detection.
- ``tx.category`` — ``id`` and ``name`` only; the primary aggregation dimension.

Fields deliberately **not read** (incomplete list):

- ``tx.description`` — raw string; fragile and provider-specific.
- ``tx.transaction_timestamp`` — authorization date; not used (cadence keys on settlement).
- ``tx.location`` — location data is not needed and is explicitly excluded per 1033.
- ``tx.account_id``, ``tx.status``, ``tx.nickname``, and all other fields.

Determinism guarantee
----------------------
Given identical inputs ``(transactions, as_of, lookback_months)`` the service always returns an
identical :class:`~banking_client.analytics.results.SpendingAnalysis`.  There is no randomness,
no LLM call, and no wall-clock read inside the pure detection functions.  The ``as_of`` date is
injectable so tests can fix it to the fixture anchor without relying on ``datetime.now()``.

Auth + audit inheritance
--------------------------
The service delegates all data access to
:meth:`~banking_client.client.transactions.TransactionsClient.get_transactions` (and optionally
:meth:`~banking_client.client.accounts.AccountsClient.get_accounts`), so every request goes
through the standard auth guard and emits an audit event on the injected trails.

Detection algorithm
--------------------
See :meth:`SpendingService.analyze_spending` for the step-by-step description.
The key insight: fixed costs are identified *structurally* — the same payee appearing on a
monthly cadence is classified as fixed regardless of its provider-supplied category label.
A hardcoded category allowlist is deliberately avoided (same philosophy as the income service).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Final

from banking_client.analytics._recurrence import (
    REGULARITY_THRESHOLD,
    _decimal_median,
    _detect_cadence,
    _normalize_payee,
    _regularity,
    _to_monthly,
    _window_start,
)
from banking_client.analytics.results import (
    NotableItem,
    NotableKind,
    PayCadence,
    RecurringCost,
    SpendCategorySummary,
    SpendingAnalysis,
    SpendingStatus,
)
from banking_client.client.accounts import AccountsClient, default_accounts_client
from banking_client.client.transactions import TransactionsClient, default_transactions_client
from banking_client.models.enums import AccountType, DebitCreditMemo, TransactionStatus
from banking_client.models.transaction import Transaction
from common.audit import AuditTrail

# ---------------------------------------------------------------------------
# Tunable constants
# ---------------------------------------------------------------------------

MIN_RECURRING_OCCURRENCES: Final[int] = 3
"""Minimum occurrences in the lookback window for a (category, payee) group to be fixed."""

OUTLIER_MULTIPLE: Final[Decimal] = Decimal("3.0")
"""An amount exceeding this multiple of the category variable median is a LARGE_ONE_OFF."""

MIN_SAMPLES_FOR_OUTLIER: Final[int] = 4
"""Minimum variable transactions per category before outlier detection is attempted."""

_TRANSFER_CATEGORY_ID: Final[str] = "CAT-TRANSFER"
"""Category id used by the fixture generator for self-transfers (savings, internal)."""

_REFUND_CATEGORY_ID: Final[str] = "CAT-REFUND"
"""Category id for inbound refund credits that net against gross spend."""

_FETCH_PAGE_SIZE: Final[int] = 500


# ---------------------------------------------------------------------------
# Internal data structure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SpendEvent:
    """A single transaction projected to the permitted 1033 fields for spending analysis.

    Fields consumed (1033 minimization):
        - ``txn_id`` — ``tx.id`` (output-only identifier, not used in inference).
        - ``amount`` — ``tx.amount.value``.
        - ``posted`` — ``tx.posted_timestamp``.
        - ``payee`` — ``tx.payee`` (counterparty, for recurring-cost detection).
        - ``category_id`` — ``tx.category.id`` (aggregation key).
        - ``category_name`` — ``tx.category.name`` (human-readable label).
        - ``is_credit`` — derived from ``tx.debit_credit_memo``; True for REFUND CREDITs.

    Fields deliberately **not read**:
        ``tx.description``, ``tx.transaction_timestamp``, ``tx.location``,
        ``tx.account_id``, ``tx.status``, ``tx.nickname``, and all other fields.
        Location is explicitly excluded per 1033 data-minimization requirements.
    """

    txn_id: str
    amount: Decimal
    posted: datetime
    payee: str | None
    category_id: str | None
    category_name: str | None
    is_credit: bool


def _to_spend_event(tx: Transaction) -> _SpendEvent | None:
    """Project a :class:`~banking_client.models.transaction.Transaction` to a minimal spend event.

    This function is the **documented 1033 minimization point**.  It reads exactly the six
    fields listed on :class:`_SpendEvent` and ignores every other field on the transaction.

    Args:
        tx: The source transaction.

    Returns:
        A :class:`_SpendEvent` for DEBIT transactions and REFUND-category CREDITs with a
        settled timestamp, or ``None`` for pending transactions and all other CREDITs.
    """
    posted = tx.posted_timestamp
    if posted is None:
        return None  # Pending — no settled timestamp yet.
    is_credit = tx.debit_credit_memo is DebitCreditMemo.CREDIT
    cat_id = tx.category.id if tx.category is not None else None
    # Keep DEBITs (spend) and REFUND credits (to net against spend); discard all other CREDITs.
    if is_credit and cat_id != _REFUND_CATEGORY_ID:
        return None
    return _SpendEvent(
        txn_id=tx.id,
        amount=tx.amount.value,
        posted=posted,
        payee=tx.payee,
        category_id=cat_id,
        category_name=tx.category.name if tx.category is not None else None,
        is_credit=is_credit,
    )


# ---------------------------------------------------------------------------
# Pure helper functions (all unit-testable with no I/O)
# ---------------------------------------------------------------------------


def _is_transfer(event: _SpendEvent) -> bool:
    """Return ``True`` if the event is a self-transfer routed to the transfers bucket.

    Matches by category id (``CAT-TRANSFER``) or normalized payee (``INTERNAL TRANSFER``).
    Both conditions are checked so transfers without a category still land in the right bucket.

    Args:
        event: The spend event to test (must be a DEBIT; CREDITs are already partitioned out).

    Returns:
        ``True`` when the event is a self-transfer and should be excluded from spend figures.
    """
    return event.category_id == _TRANSFER_CATEGORY_ID or _normalize_payee(event.payee) == "INTERNAL TRANSFER"


def _classify_group_as_recurring(
    category_id: str,
    category_name: str,
    payee: str,
    events: list[_SpendEvent],
) -> RecurringCost | None:
    """Classify a single ``(category, payee)`` group as a recurring fixed cost or variable spend.

    A group is fixed when:

    - It has at least :data:`MIN_RECURRING_OCCURRENCES` occurrences in the window.
    - The median inter-occurrence gap falls in a recognized cadence bucket (weekly/biweekly/monthly).
    - At least :data:`~banking_client.analytics._recurrence.REGULARITY_THRESHOLD` of the gaps
      are within ±25 % of the bucket period (jitter-robust: utilities still qualify).

    Args:
        category_id: Stable category identifier.
        category_name: Human-readable category label.
        payee: Normalized payee name.
        events: All occurrences of this ``(category, payee)`` group in the lookback window.

    Returns:
        A :class:`~banking_client.analytics.results.RecurringCost` when the group qualifies, or
        ``None`` when it should be treated as variable spend.
    """
    if len(events) < MIN_RECURRING_OCCURRENCES:
        return None
    sorted_events = sorted(events, key=lambda e: e.posted)
    gaps = [
        (sorted_events[i].posted - sorted_events[i - 1].posted).total_seconds() / 86400.0
        for i in range(1, len(sorted_events))
    ]
    cadence, period_days = _detect_cadence(gaps)
    if cadence is PayCadence.IRREGULAR:
        return None
    reg = _regularity(gaps, period_days)
    if reg < REGULARITY_THRESHOLD:
        return None
    amounts = [e.amount for e in sorted_events]
    avg = _decimal_median(amounts)
    monthly = _to_monthly(avg, cadence)
    return RecurringCost(
        payee=payee,
        category_id=category_id,
        category_name=category_name,
        cadence=cadence,
        average_amount=avg,
        estimated_monthly_amount=monthly,
        occurrence_count=len(events),
        supporting_transaction_ids=tuple(e.txn_id for e in sorted_events),
    )


def _detect_outliers(events: list[_SpendEvent]) -> frozenset[str]:
    """Return the transaction ids of statistical outliers in a variable-spend pool.

    An event is an outlier when its amount exceeds :data:`OUTLIER_MULTIPLE` × the pool's median
    amount.  Detection is only attempted when there are at least :data:`MIN_SAMPLES_FOR_OUTLIER`
    events; otherwise the pool is too small for a meaningful median.

    Args:
        events: Variable-spend events for a single category (across all payees).

    Returns:
        Set of ``txn_id`` strings for events whose amounts qualify as outliers.  Empty when
        the pool is too small or no amount exceeds the threshold.
    """
    if len(events) < MIN_SAMPLES_FOR_OUTLIER:
        return frozenset()
    amounts = [e.amount for e in events]
    median = _decimal_median(amounts)
    if median == Decimal("0"):
        return frozenset()
    threshold = median * OUTLIER_MULTIPLE
    return frozenset(e.txn_id for e in events if e.amount > threshold)


def _q(amount: Decimal) -> Decimal:
    """Quantize a Decimal to two decimal places (ROUND_HALF_UP)."""
    return amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class SpendingService:
    """Deterministic spending-analysis service.

    Analyses a customer's POSTED debit activity from FDX transaction history using only the
    1033-minimum set of transaction fields (see module docstring).  All data access is delegated
    to the injected :class:`~banking_client.client.transactions.TransactionsClient` (and
    optionally :class:`~banking_client.client.accounts.AccountsClient`), which carry their own
    auth guards and audit trails.

    Args:
        transactions_client: Handles transaction fetching and enforces auth on every call.
        accounts_client: Required for :meth:`analyze_spending` when *account_id* is omitted.
            The service automatically selects the customer's CHECKING accounts.

    Example::

        svc = default_spending_service()
        analysis = await svc.analyze_spending(
            "tok_cust_002", as_of=datetime(2026, 6, 30, tzinfo=UTC)
        )
        print(analysis.status, analysis.typical_monthly_spend)
    """

    def __init__(
        self,
        transactions_client: TransactionsClient,
        accounts_client: AccountsClient | None = None,
    ) -> None:
        """Store the injected clients.

        Args:
            transactions_client: Transaction client with auth + audit.
            accounts_client: Account client; only needed when *account_id* is omitted.
        """
        self._tx_client = transactions_client
        self._acct_client = accounts_client

    async def analyze_spending(
        self,
        token: str,
        account_id: str | None = None,
        *,
        lookback_months: int = 12,
        as_of: datetime | None = None,
    ) -> SpendingAnalysis:
        """Analyse spending patterns from the transaction history of one or more accounts.

        Detection pipeline:

        1. **Resolve accounts.** If *account_id* is given, analyse that account only.
           Otherwise list the customer's accounts (requires ACCOUNTS scope) and select all
           CHECKING accounts.
        2. **Fetch & minimize.** Paginate all POSTED transactions in the lookback window per
           account, projecting each into :class:`_SpendEvent` (the 1033 minimization step).
           Keeps DEBITs and REFUND-category CREDITs; discards all other CREDITs and pending.
        3. **Partition.** Separates events into three buckets: transfers (category
           ``CAT-TRANSFER`` or payee ``INTERNAL TRANSFER``), refunds (REFUND-category CREDITs),
           and spend (remaining DEBITs).
        4. **Group spend by ``(category_id, normalized payee)``.** For each group, attempt
           :func:`_classify_group_as_recurring`.  Groups that clear the cadence + regularity bar
           become :class:`~banking_client.analytics.results.RecurringCost` entries.
        5. **Outlier flagging.** For each category, collect all variable-spend events and run
           :func:`_detect_outliers`.  Flagged amounts are listed as
           :attr:`~banking_client.analytics.results.NotableKind.LARGE_ONE_OFF` and excluded from
           :attr:`~banking_client.analytics.results.SpendingAnalysis.variable_monthly_total`.
        6. **Aggregate and assemble.** Compute gross/net totals, fixed/variable monthly averages,
           per-category breakdowns, and the complete :class:`SpendingAnalysis`.

        Args:
            token: Opaque bearer token passed to every underlying client call.
            account_id: Specific account to analyse.  When ``None`` the service lists the
                customer's accounts and selects CHECKING accounts automatically (requires the
                token to hold ACCOUNTS scope).
            lookback_months: Number of calendar months of history to analyse.  Default is 12.
            as_of: Upper bound of the lookback window; defaults to ``datetime.now(UTC)``.
                Inject a fixed datetime in tests for determinism.

        Returns:
            A :class:`~banking_client.analytics.results.SpendingAnalysis` with status, category
            breakdown, recurring costs, and notable items.

        Raises:
            AuthenticationError: Token unknown or expired (propagated from the underlying client).
            AuthorizationError: Token lacks TRANSACTIONS scope, or ACCOUNTS scope when
                *account_id* is omitted (propagated from the underlying client).
            ValueError: *accounts_client* was not supplied and *account_id* is ``None``.
        """
        effective_as_of = as_of if as_of is not None else datetime.now(UTC)

        # ------------------------------------------------------------------
        # 1. Resolve account ids.
        # ------------------------------------------------------------------
        account_ids: tuple[str, ...]
        if account_id is not None:
            account_ids = (account_id,)
        else:
            if self._acct_client is None:
                raise ValueError("accounts_client is required when account_id is omitted")
            accts_page = await self._acct_client.get_accounts(token, limit=100)
            checking = [a for a in accts_page.items if a.account_type is AccountType.CHECKING]
            account_ids = tuple(a.id for a in checking)

        if not account_ids:
            return _empty_result(effective_as_of, lookback_months, account_ids)

        # ------------------------------------------------------------------
        # 2. Fetch & minimize: collect all spend/refund events across accounts.
        # ------------------------------------------------------------------
        window_start_dt = _window_start(effective_as_of, lookback_months)
        all_events: list[_SpendEvent] = []

        for acct_id in account_ids:
            page_key: str | None = None
            while True:
                page = await self._tx_client.get_transactions(
                    token,
                    acct_id,
                    start_time=window_start_dt,
                    end_time=effective_as_of,
                    status=TransactionStatus.POSTED,
                    limit=_FETCH_PAGE_SIZE,
                    page_key=page_key,
                )
                for tx in page.items:
                    event = _to_spend_event(tx)
                    if event is not None:
                        all_events.append(event)
                if page.page.next_offset is None:
                    break
                page_key = page.page.next_offset

        if not all_events:
            return _empty_result(effective_as_of, lookback_months, account_ids)

        # ------------------------------------------------------------------
        # 3. Partition into transfers, refunds, and spend.
        # ------------------------------------------------------------------
        transfers: list[_SpendEvent] = []
        refunds: list[_SpendEvent] = []
        spend_events: list[_SpendEvent] = []

        for ev in all_events:
            if ev.is_credit:
                refunds.append(ev)
            elif _is_transfer(ev):
                transfers.append(ev)
            else:
                spend_events.append(ev)

        if not spend_events:
            return _empty_result(effective_as_of, lookback_months, account_ids)

        # ------------------------------------------------------------------
        # 4. Group spend by (category_id, normalized_payee) and classify.
        # ------------------------------------------------------------------
        groups: defaultdict[tuple[str, str], list[_SpendEvent]] = defaultdict(list)
        cat_names: dict[str, str] = {}
        for ev in spend_events:
            cat_key = ev.category_id or "UNKNOWN"
            payee_key = _normalize_payee(ev.payee)
            groups[(cat_key, payee_key)].append(ev)
            if cat_key not in cat_names and ev.category_name is not None:
                cat_names[cat_key] = ev.category_name

        recurring_costs: list[RecurringCost] = []
        fixed_txn_ids: set[str] = set()

        for (cat_id, payee), g_events in sorted(groups.items()):
            cat_name = cat_names.get(cat_id, cat_id)
            rc = _classify_group_as_recurring(cat_id, cat_name, payee, g_events)
            if rc is not None:
                recurring_costs.append(rc)
                fixed_txn_ids.update(rc.supporting_transaction_ids)

        # ------------------------------------------------------------------
        # 5. Outlier detection on variable spend, per category.
        # ------------------------------------------------------------------
        variable_events = [ev for ev in spend_events if ev.txn_id not in fixed_txn_ids]
        cat_variable: defaultdict[str, list[_SpendEvent]] = defaultdict(list)
        for ev in variable_events:
            cat_variable[ev.category_id or "UNKNOWN"].append(ev)

        outlier_ids: set[str] = set()
        for _cat_id, cat_evs in cat_variable.items():
            outlier_ids.update(_detect_outliers(cat_evs))

        # ------------------------------------------------------------------
        # 6. Aggregate and assemble.
        # ------------------------------------------------------------------
        months = max(lookback_months, 1)

        total_gross_spend = _q(sum((ev.amount for ev in spend_events), Decimal("0")))
        total_refunds_val = _q(sum((ev.amount for ev in refunds), Decimal("0")))
        total_net_spend = _q(total_gross_spend - total_refunds_val)
        total_transfers = _q(sum((ev.amount for ev in transfers), Decimal("0")))
        transfers_monthly_total = _q(total_transfers / Decimal(months))

        fixed_monthly_total = _q(sum((rc.estimated_monthly_amount for rc in recurring_costs), Decimal("0")))

        outlier_total = _q(sum((ev.amount for ev in spend_events if ev.txn_id in outlier_ids), Decimal("0")))
        variable_total_gross = _q(sum((ev.amount for ev in variable_events), Decimal("0")))
        variable_monthly_total = _q((variable_total_gross - outlier_total) / Decimal(months))
        typical_monthly_spend = _q(fixed_monthly_total + variable_monthly_total)

        # Per-category summary.
        fixed_cat_ids: set[str] = {rc.category_id for rc in recurring_costs}
        all_cat_ids = sorted({ev.category_id or "UNKNOWN" for ev in spend_events})

        cat_summaries: list[SpendCategorySummary] = []
        for cat_id in all_cat_ids:
            cat_evs = [ev for ev in spend_events if (ev.category_id or "UNKNOWN") == cat_id]
            cat_outlier_total = sum((ev.amount for ev in cat_evs if ev.txn_id in outlier_ids), Decimal("0"))
            cat_total = sum((ev.amount for ev in cat_evs), Decimal("0"))
            cat_avg = _q((cat_total - cat_outlier_total) / Decimal(months))
            cat_summaries.append(
                SpendCategorySummary(
                    category_id=cat_id,
                    category_name=cat_names.get(cat_id, cat_id),
                    total_spend=_q(cat_total),
                    recurring_monthly_average=cat_avg,
                    transaction_count=len(cat_evs),
                    is_fixed=cat_id in fixed_cat_ids,
                    supporting_transaction_ids=tuple(ev.txn_id for ev in cat_evs),
                )
            )

        # Notable items: LARGE_ONE_OFF + REFUND.
        notable: list[NotableItem] = []
        for ev in sorted(spend_events, key=lambda e: e.posted):
            if ev.txn_id not in outlier_ids:
                continue
            cat_pool = cat_variable.get(ev.category_id or "UNKNOWN", [])
            cat_median = _decimal_median([e.amount for e in cat_pool])
            if cat_median > Decimal("0"):
                multiple = (ev.amount / cat_median).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
            else:
                multiple = Decimal("0")
            notable.append(
                NotableItem(
                    transaction_id=ev.txn_id,
                    kind=NotableKind.LARGE_ONE_OFF,
                    payee=_normalize_payee(ev.payee),
                    category_id=ev.category_id,
                    category_name=ev.category_name,
                    amount=ev.amount,
                    posted=ev.posted,
                    note=f"{multiple}× category median; excluded from variable avg",
                )
            )
        for ev in sorted(refunds, key=lambda e: e.posted):
            notable.append(
                NotableItem(
                    transaction_id=ev.txn_id,
                    kind=NotableKind.REFUND,
                    payee=_normalize_payee(ev.payee),
                    category_id=ev.category_id,
                    category_name=ev.category_name,
                    amount=ev.amount,
                    posted=ev.posted,
                    note="Refund credit netted against gross spend in total_net_spend",
                )
            )

        return SpendingAnalysis(
            status=SpendingStatus.ANALYZED,
            as_of=effective_as_of,
            lookback_months=lookback_months,
            account_ids=account_ids,
            total_gross_spend=total_gross_spend,
            total_refunds=total_refunds_val,
            total_net_spend=total_net_spend,
            fixed_monthly_total=fixed_monthly_total,
            variable_monthly_total=variable_monthly_total,
            typical_monthly_spend=typical_monthly_spend,
            transfers_monthly_total=transfers_monthly_total,
            category_breakdown=tuple(cat_summaries),
            recurring_costs=tuple(recurring_costs),
            notable_items=tuple(notable),
        )


def _empty_result(as_of: datetime, lookback_months: int, account_ids: tuple[str, ...]) -> SpendingAnalysis:
    """Return an INSUFFICIENT_HISTORY result with all-zero monetary fields."""
    return SpendingAnalysis(
        status=SpendingStatus.INSUFFICIENT_HISTORY,
        as_of=as_of,
        lookback_months=lookback_months,
        account_ids=account_ids,
        total_gross_spend=Decimal("0.00"),
        total_refunds=Decimal("0.00"),
        total_net_spend=Decimal("0.00"),
        fixed_monthly_total=Decimal("0.00"),
        variable_monthly_total=Decimal("0.00"),
        typical_monthly_spend=Decimal("0.00"),
        transfers_monthly_total=Decimal("0.00"),
        category_breakdown=(),
        recurring_costs=(),
        notable_items=(),
    )


def default_spending_service(*, trail: AuditTrail | None = None) -> SpendingService:
    """Return a :class:`SpendingService` wired to the committed fixture data.

    Both underlying clients are wired to the same *trail* so all audit events from a single
    logical request flow to the same sink in tests.

    Args:
        trail: Optional audit trail shared by both underlying clients.  Pass
            ``AuditTrail(sink=ListSink())`` in tests to capture and assert events without stdout
            noise.

    Returns:
        A fully wired :class:`SpendingService` backed by fixture data.

    Example::

        svc = default_spending_service(trail=AuditTrail(sink=ListSink()))
        analysis = await svc.analyze_spending("tok_cust_002")
    """
    return SpendingService(
        transactions_client=default_transactions_client(trail=trail),
        accounts_client=default_accounts_client(trail=trail),
    )
