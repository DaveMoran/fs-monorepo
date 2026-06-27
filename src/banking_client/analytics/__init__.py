"""Deterministic analytics services for Open Banking.

This subpackage implements three complementary analytics layers — income determination,
spending analysis, and savings-capacity estimation — all of which are the deterministic,
LLM-free layer that agents and eval harnesses reason about.  Every conclusion is grounded
in transaction ids so callers can verify the reasoning.

1033 data-minimization contracts
----------------------------------
Each service applies its own minimization contract documented at the ``_to_*_event`` projection
point in its module.  Key differences between the three:

**Income** (``income.py``) — reads **four** fields only:
  ``amount``, ``posted_timestamp``, ``debit_credit_memo``, ``payee``.
  ``category`` is **never read**; income is inferred structurally (cadence + amount stability +
  counterparty exclusion).

**Spending** (``spending.py``) — reads **five** fields:
  ``amount``, ``posted_timestamp``, ``debit_credit_memo``, ``payee``, **and** ``category``
  (``id`` + ``name`` only — the primary aggregation dimension).
  ``description``, ``transaction_timestamp``, and ``location`` are **never read** by either
  service.

**Savings** (``savings.py``) — reads **no transaction fields directly**.  It composes the
  income and spending services (inheriting their auth, audit, and minimization) and performs
  a single, minimal account-metadata read (``account_type`` + ``balances``) for debt detection.

Public surface — income
-----------------------
- :class:`~banking_client.analytics.income.IncomeService`
- :func:`~banking_client.analytics.income.default_income_service`
- :class:`~banking_client.analytics.results.IncomeEstimate`,
  :class:`~banking_client.analytics.results.IncomeSource`,
  :class:`~banking_client.analytics.results.RejectedCandidate`
- Enums: :class:`~banking_client.analytics.results.PayCadence`,
  :class:`~banking_client.analytics.results.ConfidenceLevel`,
  :class:`~banking_client.analytics.results.IncomeStatus`,
  :class:`~banking_client.analytics.results.RejectionReason`

Public surface — spending
-------------------------
- :class:`~banking_client.analytics.spending.SpendingService`
- :func:`~banking_client.analytics.spending.default_spending_service`
- :class:`~banking_client.analytics.results.SpendingAnalysis`,
  :class:`~banking_client.analytics.results.SpendCategorySummary`,
  :class:`~banking_client.analytics.results.RecurringCost`,
  :class:`~banking_client.analytics.results.NotableItem`
- Enums: :class:`~banking_client.analytics.results.SpendingStatus`,
  :class:`~banking_client.analytics.results.NotableKind`

Public surface — savings
------------------------
- :class:`~banking_client.analytics.savings.SavingsCapacityService`
- :func:`~banking_client.analytics.savings.default_savings_service`
- :func:`~banking_client.analytics.savings.render_reasoning`
- :class:`~banking_client.analytics.results.SavingsCapacityEstimate`,
  :class:`~banking_client.analytics.results.DebtAccountRef`,
  :class:`~banking_client.analytics.results.ReasoningStep`
- Enums: :class:`~banking_client.analytics.results.SavingsCapacityStatus`,
  :class:`~banking_client.analytics.results.SavingsPriority`,
  :class:`~banking_client.analytics.results.ReasoningCode`
"""

from __future__ import annotations

from banking_client.analytics.income import IncomeService, default_income_service
from banking_client.analytics.results import (
    CONSERVATIVE_FRACTION,
    LOW_CONFIDENCE_FRACTION,
    ROUNDING_INCREMENT,
    ConfidenceLevel,
    DebtAccountRef,
    IncomeEstimate,
    IncomeSource,
    IncomeStatus,
    NotableItem,
    NotableKind,
    PayCadence,
    ReasoningCode,
    ReasoningStep,
    RecurringCost,
    RejectedCandidate,
    RejectionReason,
    SavingsCapacityEstimate,
    SavingsCapacityStatus,
    SavingsPriority,
    SpendCategorySummary,
    SpendingAnalysis,
    SpendingStatus,
)
from banking_client.analytics.savings import (
    SavingsCapacityService,
    default_savings_service,
    render_reasoning,
)
from banking_client.analytics.spending import SpendingService, default_spending_service

__all__: list[str] = [
    # Income
    "ConfidenceLevel",
    "IncomeEstimate",
    "IncomeService",
    "IncomeSource",
    "IncomeStatus",
    "PayCadence",
    "RejectedCandidate",
    "RejectionReason",
    "default_income_service",
    # Spending
    "NotableItem",
    "NotableKind",
    "RecurringCost",
    "SpendCategorySummary",
    "SpendingAnalysis",
    "SpendingService",
    "SpendingStatus",
    "default_spending_service",
    # Savings
    "CONSERVATIVE_FRACTION",
    "DebtAccountRef",
    "LOW_CONFIDENCE_FRACTION",
    "ReasoningCode",
    "ReasoningStep",
    "ROUNDING_INCREMENT",
    "SavingsCapacityEstimate",
    "SavingsCapacityService",
    "SavingsCapacityStatus",
    "SavingsPriority",
    "default_savings_service",
    "render_reasoning",
]
