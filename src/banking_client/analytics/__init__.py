"""Deterministic analytics services for Open Banking.

This subpackage implements two complementary analytics layers — income determination and
spending analysis — both of which are the deterministic, LLM-free layer that agents and eval
harnesses reason about.  Every conclusion is grounded in transaction ids so callers can verify
the reasoning.

1033 data-minimization contracts
----------------------------------
Each service applies its own minimization contract documented at the ``_to_*_event`` projection
point in its module.  Key differences between the two:

**Income** (``income.py``) — reads **four** fields only:
  ``amount``, ``posted_timestamp``, ``debit_credit_memo``, ``payee``.
  ``category`` is **never read**; income is inferred structurally (cadence + amount stability +
  counterparty exclusion).

**Spending** (``spending.py``) — reads **five** fields:
  ``amount``, ``posted_timestamp``, ``debit_credit_memo``, ``payee``, **and** ``category``
  (``id`` + ``name`` only — the primary aggregation dimension).
  ``description``, ``transaction_timestamp``, and ``location`` are **never read** by either
  service.

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
"""

from __future__ import annotations

from banking_client.analytics.income import IncomeService, default_income_service
from banking_client.analytics.results import (
    ConfidenceLevel,
    IncomeEstimate,
    IncomeSource,
    IncomeStatus,
    NotableItem,
    NotableKind,
    PayCadence,
    RecurringCost,
    RejectedCandidate,
    RejectionReason,
    SpendCategorySummary,
    SpendingAnalysis,
    SpendingStatus,
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
]
