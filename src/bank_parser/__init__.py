"""Parse Russian bank exports into a canonical transaction CSV.

Public API::

    from bank_parser import Transaction, read_table, write_transactions
    from bank_parser import detect_bank, get_parser
"""

from __future__ import annotations

import logging

from .banks import detect_bank, get_parser, supported_banks
from .models import Money, OperationType, Transaction
from .readers import read_table
from .writers import HEADER, write_transactions

__version__ = "1.0.0"
"""Package version (kept in sync with ``pyproject.toml``)."""

_logger = logging.getLogger(__name__)
if not any(
    isinstance(handler, logging.NullHandler)
    for handler in _logger.handlers
):
    _logger.addHandler(logging.NullHandler())

__all__ = [
    "HEADER",
    "Money",
    "OperationType",
    "Transaction",
    "__version__",
    "detect_bank",
    "get_parser",
    "read_table",
    "supported_banks",
    "write_transactions",
]
