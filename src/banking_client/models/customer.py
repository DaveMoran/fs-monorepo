"""Customer model.

Maps to the FDX v6.5 ``Customer`` resource plus the accounts the customer owns.
"""

from __future__ import annotations

from banking_client.models.account import Account
from banking_client.models.base import FDXBaseModel


class Customer(FDXBaseModel):
    """A banking customer and the accounts they own (FDX ``Customer``)."""

    id: str
    """Provider-assigned stable customer identifier (FDX ``customerId``)."""
    name: str
    """The customer's full name."""
    accounts: list[Account] = []
    """The accounts owned by this customer. Empty if none are linked or shared."""
