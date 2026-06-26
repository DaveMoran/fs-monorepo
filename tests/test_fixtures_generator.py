"""Tests for the dev-only synthetic FDX data generator.

Covers determinism, spec-conformance of the committed dataset (round-tripping JSON back through
the real models), FDX wire-format details, the tricky-case content invariants that keep income/
spending detection honest, and the decoupling guarantee that nothing under ``src/`` imports the
``fixtures`` package.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from fixtures.generator.__main__ import main
from fixtures.generator.build import CustomerDataset, build_dataset
from fixtures.generator.config import GenerationConfig

from banking_client.models import Customer, PaginatedResponse, Transaction

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "fixtures" / "data"
SRC_DIR = REPO_ROOT / "src"

PAYROLL = "CAT-PAYROLL"
TRANSFER = "CAT-TRANSFER"


def _serialize(datasets: list[CustomerDataset]) -> dict[str, str]:
    blobs: dict[str, str] = {}
    for dataset in datasets:
        blobs[dataset.customer.id] = dataset.customer.model_dump_json(by_alias=True)
        for account_id, response in dataset.transactions.items():
            blobs[account_id] = response.model_dump_json(by_alias=True)
    return blobs


def _checking(datasets: list[CustomerDataset], customer_id: str) -> list[Transaction]:
    dataset = next(d for d in datasets if d.customer.id == customer_id)
    return dataset.transactions[f"{customer_id}-checking"].items


# --- determinism ---------------------------------------------------------------------------


def test_same_seed_is_deterministic() -> None:
    """Two runs with the same seed produce byte-identical serialized output."""
    assert _serialize(build_dataset(GenerationConfig(seed=42))) == _serialize(build_dataset(GenerationConfig(seed=42)))


def test_different_seed_changes_output() -> None:
    """Changing the seed changes the generated data."""
    assert _serialize(build_dataset(GenerationConfig(seed=42))) != _serialize(build_dataset(GenerationConfig(seed=7)))


# --- spec conformance of committed fixtures ------------------------------------------------


def test_committed_customers_roundtrip_through_models() -> None:
    """Every committed customer file validates back into a Customer model."""
    files = sorted((DATA_DIR / "customers").glob("*.json"))
    assert files, "no committed customer fixtures found"
    for path in files:
        Customer.model_validate_json(path.read_text())


def test_committed_transactions_roundtrip_through_models() -> None:
    """Every committed transactions file validates into a paginated Transaction response."""
    files = sorted((DATA_DIR / "transactions").glob("*.json"))
    assert files, "no committed transaction fixtures found"
    for path in files:
        PaginatedResponse[Transaction].model_validate_json(path.read_text())


# --- FDX wire format -----------------------------------------------------------------------


def test_wire_format_is_camel_case_with_string_decimals() -> None:
    """Committed JSON uses camelCase FDX keys, string Decimals, and the paginated envelope."""
    customer = json.loads((DATA_DIR / "customers" / "cust-002.json").read_text())
    account = customer["accounts"][0]
    assert "accountType" in account
    assert "accountNumberDisplay" in account
    balance = account["balances"][0]
    assert isinstance(balance["amount"]["value"], str)
    assert re.fullmatch(r"[A-Z]{3}", balance["amount"]["currency"])

    transactions = json.loads((DATA_DIR / "transactions" / "cust-002-checking.json").read_text())
    assert {"page", "items"} <= transactions.keys()
    item = transactions["items"][0]
    assert "transactionTimestamp" in item
    assert "debitCreditMemo" in item
    assert isinstance(item["amount"]["value"], str)


# --- content invariants / tricky cases -----------------------------------------------------


def test_payroll_lands_on_a_biweekly_cadence() -> None:
    """Payroll deposits are spaced exactly 14 days apart."""
    txns = _checking(build_dataset(GenerationConfig(seed=42)), "cust-001")
    paydays = sorted(t.transaction_timestamp for t in txns if t.category is not None and t.category.id == PAYROLL)
    assert len(paydays) >= 24
    gaps = {(later - earlier).days for earlier, later in zip(paydays, paydays[1:], strict=False)}
    assert gaps == {14}


def test_venmo_cashout_is_a_transfer_not_income() -> None:
    """The Venmo-style CREDIT is categorized as a transfer, not payroll income."""
    venmo = [t for t in _checking(build_dataset(GenerationConfig(seed=42)), "cust-002") if t.payee == "VENMO"]
    assert venmo
    assert all(t.category is not None and t.category.id == TRANSFER for t in venmo)
    assert all(t.debit_credit_memo.value == "CREDIT" for t in venmo)


def test_payroll_amount_steps_up_mid_history() -> None:
    """The configured raise produces exactly two payroll amounts, increasing over time."""
    txns = sorted(
        (
            t
            for t in _checking(build_dataset(GenerationConfig(seed=42)), "cust-002")
            if t.category is not None and t.category.id == PAYROLL
        ),
        key=lambda t: t.transaction_timestamp,
    )
    amounts = [t.amount.value for t in txns]
    distinct = sorted(set(amounts))
    assert len(distinct) == 2
    assert amounts[0] == distinct[0]
    assert amounts[-1] == distinct[1]


def test_pending_transactions_have_no_posted_timestamp() -> None:
    """PENDING transactions exist and carry a null posted timestamp."""
    pending = [
        t for t in _checking(build_dataset(GenerationConfig(seed=42)), "cust-003") if t.status.value == "PENDING"
    ]
    assert pending
    assert all(t.posted_timestamp is None for t in pending)


def test_freelance_income_is_irregular() -> None:
    """Freelance CREDITs are present and vary in amount (not a fixed cadence amount)."""
    freelance = [
        t
        for t in _checking(build_dataset(GenerationConfig(seed=42)), "cust-002")
        if t.category is not None and t.category.id == "CAT-FREELANCE"
    ]
    assert freelance
    assert len({t.amount.value for t in freelance}) > 1


# --- decoupling guarantee ------------------------------------------------------------------


def test_src_never_imports_fixtures() -> None:
    """Nothing under src/ imports the fixtures package, keeping the seam clean for Week 20."""
    pattern = re.compile(r"^\s*(?:from|import)\s+fixtures\b", re.MULTILINE)
    offenders = [path.name for path in SRC_DIR.rglob("*.py") if pattern.search(path.read_text())]
    assert offenders == []


# --- CLI -----------------------------------------------------------------------------------


def test_cli_writes_validatable_files(tmp_path: Path) -> None:
    """The CLI writes files into the target directory and they validate through the models."""
    exit_code = main(["--seed", "1", "--customers", "2", "--output-dir", str(tmp_path)])
    assert exit_code == 0
    customer_files = sorted((tmp_path / "customers").glob("*.json"))
    assert len(customer_files) == 2
    for path in customer_files:
        Customer.model_validate_json(path.read_text())
    for path in (tmp_path / "transactions").glob("*.json"):
        PaginatedResponse[Transaction].model_validate_json(path.read_text())
