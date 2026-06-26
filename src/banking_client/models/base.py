"""Shared base class and primitive types for the FDX model layer.

These models implement a deliberately small slice of the Financial Data Exchange
(FDX) API v6.5 "Core Exchange" surface — the subset Open Banking MCP needs. They are
pure data schemas: no HTTP, no business logic, just the typed contract that the FDX
client (deserialization target), the MCP server (tool I/O), and the agent loop
(income detection) all import.

Money handling — why ``Decimal`` and never ``float``
-----------------------------------------------------
Binary floating point cannot exactly represent most decimal fractions: ``0.1 + 0.2``
is ``0.30000000000000004``. Summing thousands of transactions in ``float`` therefore
drifts, and a ledger that does not reconcile to the cent is worthless. ``Decimal``
performs exact base-10 arithmetic, so every monetary value in this package is a
``Decimal`` (see :class:`~banking_client.models.money.Money`). Pydantic v2 serializes
``Decimal`` to a JSON *string* rather than a number, which preserves precision across a
serialize/parse round-trip; we rely on that behavior and do not override it.

Wire format
-----------
FDX JSON uses ``camelCase`` keys (``accountNumberDisplay``, ``postedTimestamp``). We
keep Pythonic ``snake_case`` field names and generate ``camelCase`` aliases via
:class:`FDXBaseModel`, so models are FDX-faithful on the wire and PEP 8 in code.

Unknown fields
--------------
Because we model only a subset, real FDX payloads carry elements we do not define. The
base config uses ``extra="ignore"`` so unmodeled fields do not break parsing.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

CurrencyCode = Annotated[str, Field(pattern=r"^[A-Z]{3}$", examples=["USD", "EUR"])]
"""An ISO 4217 three-letter currency code (e.g. ``"USD"``).

FDX uses the full ISO 4217 set (~180 codes). Modeling that as a Python ``enum`` would be
unwieldy and would reject valid codes we simply have not listed, so currency is the
deliberate exception to this package's "categorical fields are enums" rule: it is a
pattern-validated string instead. The regex enforces three uppercase letters; it does not
verify the code is an assigned ISO 4217 currency.
"""


class FDXBaseModel(BaseModel):
    """Base class for every FDX model.

    Centralizes the shared Pydantic configuration so individual models stay declarative:

    - ``alias_generator=to_camel`` + ``populate_by_name=True``: accept and emit FDX
      ``camelCase`` keys while letting Python code use ``snake_case`` field names.
    - ``extra="ignore"``: tolerate FDX fields outside this subset instead of failing.
    """

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )
