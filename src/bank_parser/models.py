"""Legacy compatibility facade for the canonical domain value objects.

v1 code imports ``Transaction`` from :mod:`bank_parser.models`; the class now
lives in :mod:`bank_parser.domain.models` and keeps the same constructor and
field order (with ``location`` appended as an optional diagnostics field).
"""

from __future__ import annotations

from .domain.models import (
    InputFormat,
    Money,
    OperationType,
    SourceLocation,
    Transaction,
)

__all__ = [
    "InputFormat",
    "Money",
    "OperationType",
    "SourceLocation",
    "Transaction",
]
