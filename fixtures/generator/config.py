"""Generation configuration and shared primitives.

Everything that controls *what* gets generated and *how reproducibly* lives here: the seed,
the customer/account/history knobs, the fixed time anchor, and the output location. Keeping
the anchor fixed (never :func:`datetime.now`) is what makes a given seed produce byte-identical
JSON — essential for reproducible tests and the future eval golden dataset.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from banking_client.models import CurrencyCode, Money

CURRENCY: CurrencyCode = "USD"
"""Single-currency dataset for now; every Money/Account uses USD."""

_CENTS = Decimal("0.01")

DEFAULT_ANCHOR: datetime = datetime(2026, 6, 30, tzinfo=UTC)
"""Fixed 'as of now' point the 24-month window counts back from.

Deliberately a constant, not ``datetime.now()`` — determinism depends on it.
"""

DEFAULT_OUTPUT_DIR: Path = Path(__file__).resolve().parent.parent / "data"
"""Where generated JSON lands: ``fixtures/data/``."""


@dataclass(frozen=True)
class GenerationConfig:
    """Knobs controlling a generation run.

    Attributes:
        seed: Seeds the single RNG threaded through the whole run.
        num_customers: How many archetype customers to emit (capped at the number defined).
        history_months: Length of the transaction window in months (FDX/1033 horizon is 24).
        anchor_date: Fixed end of the window; the history spans backward from here.
        output_dir: Directory the writer persists JSON into.
    """

    seed: int = 42
    num_customers: int = 3
    history_months: int = 24
    anchor_date: datetime = DEFAULT_ANCHOR
    output_dir: Path = field(default=DEFAULT_OUTPUT_DIR)


def new_rng(config: GenerationConfig) -> random.Random:
    """Return a fresh RNG seeded from ``config``; the run threads this single instance."""
    return random.Random(config.seed)


def quantize(value: Decimal) -> Decimal:
    """Round a raw Decimal to 2 dp (half-up), the canonical money precision."""
    return value.quantize(_CENTS, rounding=ROUND_HALF_UP)


def usd(value: Decimal) -> Money:
    """Build a USD :class:`Money` from a Decimal, quantized to cents."""
    return Money(value=quantize(value), currency=CURRENCY)
