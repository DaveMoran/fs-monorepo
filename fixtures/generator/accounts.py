"""Build :class:`~banking_client.models.Account` objects from profile specs.

Balances are derived *after* transactions are synthesized so the reported AVAILABLE/CURRENT
figures are consistent with the generated history's running total at the anchor date.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from banking_client.models import Account, AccountStatus, Balance, BalanceType
from fixtures.generator.config import CURRENCY, usd
from fixtures.generator.profiles import AccountSpec


def build_balances(current: Decimal, available: Decimal, as_of: datetime) -> list[Balance]:
    """Build the AVAILABLE and CURRENT balance pair reported for an account."""
    return [
        Balance(balance_type=BalanceType.AVAILABLE, amount=usd(available), as_of_date=as_of),
        Balance(balance_type=BalanceType.CURRENT, amount=usd(current), as_of_date=as_of),
    ]


def build_account(spec: AccountSpec, customer_id: str, balances: list[Balance]) -> Account:
    """Assemble an :class:`Account` from its spec and computed balances."""
    return Account(
        id=f"{customer_id}-{spec.suffix}",
        account_type=spec.account_type,
        account_number_display=spec.masked_number,
        nickname=spec.nickname,
        status=AccountStatus.OPEN,
        currency=CURRENCY,
        balances=balances,
    )
