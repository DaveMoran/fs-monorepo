"""Fixed categorization scheme and merchant pools.

The FDX models intentionally model ``TransactionCategory`` as a free-form object (``id`` +
``name``), not an enum — there is no closed category set to reuse. To keep fixtures stable and
queryable (so later income/spending detection and eval logic can assert against known values),
this module owns a small *fixed catalog* that stands in for a real provider's categorization
scheme. Every generated transaction draws its category from here.
"""

from __future__ import annotations

from typing import Final

from banking_client.models import TransactionCategory


def _category(category_id: str, name: str) -> TransactionCategory:
    return TransactionCategory(id=category_id, name=name)


# Income-side categories.
PAYROLL: Final = _category("CAT-PAYROLL", "Payroll")
FREELANCE: Final = _category("CAT-FREELANCE", "Freelance Income")
TRANSFER: Final = _category("CAT-TRANSFER", "Transfer")
REFUND: Final = _category("CAT-REFUND", "Refund")

# Spend-side categories.
RENT: Final = _category("CAT-RENT", "Rent")
UTILITIES: Final = _category("CAT-UTILITIES", "Utilities")
SUBSCRIPTION: Final = _category("CAT-SUBSCRIPTION", "Subscription")
GROCERIES: Final = _category("CAT-GROCERIES", "Groceries")
DINING: Final = _category("CAT-DINING", "Dining")
SHOPPING: Final = _category("CAT-SHOPPING", "Shopping")

MERCHANTS: Final[dict[str, tuple[str, ...]]] = {
    GROCERIES.id: ("Trader Joe's", "Safeway", "Whole Foods", "Costco", "Kroger"),
    DINING.id: ("Chipotle", "Blue Bottle Coffee", "Olive Garden", "Sweetgreen", "Local Diner"),
    SHOPPING.id: ("Amazon", "Target", "Best Buy", "REI", "Nordstrom"),
}
"""Per-category payee pools for variable discretionary spend."""
