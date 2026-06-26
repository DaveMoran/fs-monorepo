"""FDX consent data clusters.

In the FDX consent model a user grants a third party access to *categories* of their financial
data, not just individual accounts. These categories are called *data clusters*. A bearer token
is authorised for a specific set of clusters; requesting data outside that set is rejected even
if the account id is within scope.

This enum is intentionally a narrow subset of the clusters FDX v6.5 defines — only those the
Open Banking MCP "Core Exchange" slice targets. INVESTMENTS is modelled now so the consent
layer can reject requests to that cluster before any investment tool exists, demonstrating
narrow-scope enforcement from day one.
"""

from __future__ import annotations

from enum import StrEnum


class DataCluster(StrEnum):
    """A category of financial data that may be permissioned in a consent grant.

    Members map 1-to-1 to the MCP tools the banking client will expose:

    - :attr:`ACCOUNTS` — account details and balances (``get_customer``, ``get_accounts``,
      ``get_account``).
    - :attr:`TRANSACTIONS` — transaction history (``get_transactions``).
    - :attr:`INVESTMENTS` — holdings and positions; no MCP tool exists yet. Modelled now so
      consent scopes can explicitly exclude it and tests can assert rejection.
    """

    ACCOUNTS = "ACCOUNTS"
    """Account details and balance data.

    Covers: customer profile, account list, individual account detail, and associated balances.
    Granting this cluster does not imply access to transaction history.
    """

    TRANSACTIONS = "TRANSACTIONS"
    """Transaction history for deposit and credit accounts.

    Covers: posted and pending transactions across the permissioned accounts. Requires
    :attr:`ACCOUNTS` to be meaningful in practice (you need to know account ids), but the
    authorisation check treats each cluster independently.
    """

    INVESTMENTS = "INVESTMENTS"
    """Investment account holdings and positions.

    No MCP tool is implemented yet. This cluster exists so consent scopes can declare that
    investment data is *not* granted, and the authorisation guard can enforce that boundary
    before the tool exists. A token for a customer with an INVESTMENT account but without this
    cluster should be rejected when accessing ``cust-NNN-retirement``.
    """
