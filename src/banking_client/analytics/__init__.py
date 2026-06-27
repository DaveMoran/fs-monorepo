"""Deterministic income-determination analytics for Open Banking.

This subpackage implements the analytics layer that infers a customer's regular income from FDX
transaction history.  It is the deterministic, LLM-free layer that agents and eval harnesses
reason about — every conclusion is grounded in transaction ids so callers can verify the
reasoning.

1033 data-minimization contract
---------------------------------
This subpackage intentionally limits itself to four transaction fields:

- ``amount`` (``tx.amount.value``)
- ``posted_timestamp``
- ``debit_credit_memo``
- ``payee``

Plus ``id`` for explainability output only.  The fields ``category``, ``description``,
``transaction_timestamp``, ``location``, and all others are **never read**.  Income is inferred
*structurally* (cadence + amount stability + counterparty) rather than from provider-supplied
categorization labels.

Public surface
--------------
- :class:`~banking_client.analytics.income.IncomeService` — the service; wire to
  :class:`~banking_client.client.TransactionsClient` (+ optionally
  :class:`~banking_client.client.AccountsClient` for ``account_id`` auto-discovery).
- :func:`~banking_client.analytics.income.default_income_service` — factory wired to the
  committed fixture data.
- Result models: :class:`~banking_client.analytics.results.IncomeEstimate`,
  :class:`~banking_client.analytics.results.IncomeSource`,
  :class:`~banking_client.analytics.results.RejectedCandidate`.
- Enums: :class:`~banking_client.analytics.results.PayCadence`,
  :class:`~banking_client.analytics.results.ConfidenceLevel`,
  :class:`~banking_client.analytics.results.IncomeStatus`,
  :class:`~banking_client.analytics.results.RejectionReason`.
"""

from __future__ import annotations

from banking_client.analytics.income import IncomeService, default_income_service
from banking_client.analytics.results import (
    ConfidenceLevel,
    IncomeEstimate,
    IncomeSource,
    IncomeStatus,
    PayCadence,
    RejectedCandidate,
    RejectionReason,
)

__all__: list[str] = [
    "ConfidenceLevel",
    "IncomeEstimate",
    "IncomeService",
    "IncomeSource",
    "IncomeStatus",
    "PayCadence",
    "RejectedCandidate",
    "RejectionReason",
    "default_income_service",
]
