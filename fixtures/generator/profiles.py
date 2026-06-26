"""The three customer archetypes, described declaratively.

Profiles are *data*, not logic: each one specifies the accounts a customer holds and the shape
of their cash flow (payroll, recurring bills, discretionary spend, and which tricky cases to
inject). :mod:`fixtures.generator.transactions` interprets these specs into concrete
:class:`~banking_client.models.Transaction` streams.

Distinct ``customer_id`` values give later RBAC tests stable subjects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from banking_client.models import AccountType, TransactionCategory
from fixtures.generator import catalog


@dataclass(frozen=True)
class AccountSpec:
    """One account a customer holds."""

    suffix: str
    """Stable per-customer account id suffix (e.g. ``"checking"``)."""
    account_type: AccountType
    masked_number: str
    nickname: str | None = None
    is_primary: bool = False
    """The checking account where payroll lands and bills/discretionary are drawn."""


@dataclass(frozen=True)
class PayrollSpec:
    """Recurring biweekly salary deposit."""

    payee: str
    base_amount: Decimal
    raise_amount: Decimal | None = None
    """If set, payroll steps to this amount partway through the window (a mid-history raise)."""
    raise_after_fraction: float = 0.5
    """Fraction of the window after which the raise takes effect."""


@dataclass(frozen=True)
class BillSpec:
    """A recurring monthly debit on a fixed day."""

    category: TransactionCategory
    payee: str
    amount: Decimal
    day_of_month: int
    jitter: Decimal = Decimal("0")
    """Max absolute amount wobble per occurrence (e.g. utilities); 0 means fixed."""


@dataclass(frozen=True)
class DiscretionarySpec:
    """A stream of variable discretionary debits in one category."""

    category: TransactionCategory
    monthly_count: int
    amount_mean: Decimal
    amount_stddev: Decimal


@dataclass(frozen=True)
class CustomerProfile:
    """Full declarative description of one synthetic customer."""

    customer_id: str
    name: str
    accounts: tuple[AccountSpec, ...]
    payroll: PayrollSpec
    bills: tuple[BillSpec, ...]
    discretionary: tuple[DiscretionarySpec, ...]
    include_venmo_fake_income: bool = False
    include_freelance: bool = False
    include_pending: bool = False
    include_large_purchase: bool = False
    include_refund: bool = False
    opening_balance: Decimal = field(default=Decimal("0"))
    """Starting checking balance at the window's beginning, before any generated activity."""


PAYCHECK_TO_PAYCHECK = CustomerProfile(
    customer_id="cust-001",
    name="Riley Nguyen",
    accounts=(AccountSpec("checking", AccountType.CHECKING, "****1001", "Everyday Checking", is_primary=True),),
    payroll=PayrollSpec(payee="ACME CORP PAYROLL", base_amount=Decimal("925.00")),
    bills=(
        BillSpec(catalog.RENT, "SUNSET APARTMENTS", Decimal("1500.00"), day_of_month=1),
        BillSpec(catalog.UTILITIES, "CITY POWER & WATER", Decimal("140.00"), day_of_month=12, jitter=Decimal("35")),
        BillSpec(catalog.SUBSCRIPTION, "NETFLIX", Decimal("15.49"), day_of_month=20),
    ),
    discretionary=(
        DiscretionarySpec(catalog.GROCERIES, monthly_count=5, amount_mean=Decimal("48"), amount_stddev=Decimal("18")),
        DiscretionarySpec(catalog.DINING, monthly_count=4, amount_mean=Decimal("22"), amount_stddev=Decimal("9")),
    ),
    include_refund=True,
    opening_balance=Decimal("320.00"),
)

FINANCIALLY_HEALTHY = CustomerProfile(
    customer_id="cust-002",
    name="Jordan Patel",
    accounts=(
        AccountSpec("checking", AccountType.CHECKING, "****2001", "Primary Checking", is_primary=True),
        AccountSpec("savings", AccountType.SAVINGS, "****2002", "Emergency Fund"),
        AccountSpec("card", AccountType.CREDIT_CARD, "****2003", "Rewards Card"),
    ),
    payroll=PayrollSpec(
        payee="GLOBEX LLC PAYROLL",
        base_amount=Decimal("1800.00"),
        raise_amount=Decimal("2050.00"),
        raise_after_fraction=0.6,
    ),
    bills=(
        BillSpec(catalog.RENT, "OAKWOOD LEASING", Decimal("2100.00"), day_of_month=1),
        BillSpec(catalog.UTILITIES, "METRO ENERGY", Decimal("180.00"), day_of_month=10, jitter=Decimal("40")),
        BillSpec(catalog.SUBSCRIPTION, "SPOTIFY", Decimal("11.99"), day_of_month=15),
        BillSpec(catalog.SUBSCRIPTION, "PLANET FITNESS", Decimal("24.99"), day_of_month=18),
    ),
    discretionary=(
        DiscretionarySpec(catalog.GROCERIES, monthly_count=6, amount_mean=Decimal("72"), amount_stddev=Decimal("25")),
        DiscretionarySpec(catalog.DINING, monthly_count=7, amount_mean=Decimal("38"), amount_stddev=Decimal("16")),
        DiscretionarySpec(catalog.SHOPPING, monthly_count=3, amount_mean=Decimal("95"), amount_stddev=Decimal("60")),
    ),
    include_venmo_fake_income=True,
    include_freelance=True,
    include_large_purchase=True,
    include_refund=True,
    opening_balance=Decimal("4200.00"),
)

HIGH_ACTIVITY = CustomerProfile(
    customer_id="cust-003",
    name="Sam Okafor",
    accounts=(
        AccountSpec("checking", AccountType.CHECKING, "****3001", "Main Checking", is_primary=True),
        AccountSpec("savings", AccountType.SAVINGS, "****3002", "High-Yield Savings"),
        AccountSpec("card", AccountType.CREDIT_CARD, "****3003", "Travel Card"),
        AccountSpec("retirement", AccountType.INVESTMENT, "****3004", "401(k)"),
    ),
    payroll=PayrollSpec(payee="INITECH PAYROLL", base_amount=Decimal("2350.00")),
    bills=(
        BillSpec(catalog.RENT, "HARBORVIEW TOWERS", Decimal("2650.00"), day_of_month=1),
        BillSpec(catalog.UTILITIES, "PACIFIC UTILITIES", Decimal("220.00"), day_of_month=9, jitter=Decimal("55")),
        BillSpec(catalog.SUBSCRIPTION, "ADOBE CC", Decimal("54.99"), day_of_month=14),
        BillSpec(catalog.SUBSCRIPTION, "NYT", Decimal("17.00"), day_of_month=22),
    ),
    discretionary=(
        DiscretionarySpec(catalog.GROCERIES, monthly_count=8, amount_mean=Decimal("64"), amount_stddev=Decimal("22")),
        DiscretionarySpec(catalog.DINING, monthly_count=12, amount_mean=Decimal("44"), amount_stddev=Decimal("19")),
        DiscretionarySpec(catalog.SHOPPING, monthly_count=6, amount_mean=Decimal("110"), amount_stddev=Decimal("70")),
    ),
    include_venmo_fake_income=True,
    include_freelance=True,
    include_pending=True,
    include_large_purchase=True,
    include_refund=True,
    opening_balance=Decimal("7800.00"),
)

PROFILES: tuple[CustomerProfile, ...] = (PAYCHECK_TO_PAYCHECK, FINANCIALLY_HEALTHY, HIGH_ACTIVITY)
"""All defined archetypes, in stable order. A run takes the first ``num_customers``."""
