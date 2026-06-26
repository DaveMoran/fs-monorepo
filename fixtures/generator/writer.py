"""Persist built datasets to FDX-shaped JSON on disk.

Output is serialized with ``by_alias=True`` so keys are camelCase FDX wire names, and with a
stable indent so committed files produce reviewable diffs. The layout maps 1:1 to the MCP tools
the future ``MockFDXClient`` will serve:

- ``data/customers/<customerId>.json`` — a :class:`~banking_client.models.Customer` with nested
  accounts (serves ``get_customer`` / ``get_accounts`` / ``get_account``).
- ``data/transactions/<accountId>.json`` — a paginated transaction response (serves
  ``get_transactions``). The account id already encodes the customer, so it is globally unique.
"""

from __future__ import annotations

from pathlib import Path

from fixtures.generator.build import CustomerDataset


def _dump_json(model_json: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(model_json + "\n", encoding="utf-8")


def write_dataset(datasets: list[CustomerDataset], output_dir: Path) -> list[Path]:
    """Write every customer and per-account transaction file; return the paths written, sorted."""
    written: list[Path] = []
    customers_dir = output_dir / "customers"
    transactions_dir = output_dir / "transactions"

    for dataset in datasets:
        customer_path = customers_dir / f"{dataset.customer.id}.json"
        _dump_json(dataset.customer.model_dump_json(by_alias=True, indent=2), customer_path)
        written.append(customer_path)

        for account_id, response in dataset.transactions.items():
            tx_path = transactions_dir / f"{account_id}.json"
            _dump_json(response.model_dump_json(by_alias=True, indent=2), tx_path)
            written.append(tx_path)

    return sorted(written)
