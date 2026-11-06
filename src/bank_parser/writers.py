"""Legacy compatibility facade for the canonical CSV writer.

New code should use :class:`bank_parser.adapters.writers.CanonicalCsvWriter`
directly.  ``HEADER`` keeps the v1 list shape and values; ``write_transactions``
delegates to a module-level writer instance.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from .adapters.writers import CanonicalCsvWriter
from .models import Transaction

__all__ = ["HEADER", "write_transactions"]

HEADER: list[str] = list(CanonicalCsvWriter.HEADER)
"""Canonical header row; the last field is an empty placeholder column."""

_WRITER = CanonicalCsvWriter()


def write_transactions(
    transactions: Iterable[Transaction], path: str | Path
) -> int:
    """Write *transactions* to *path* in the canonical CSV format.

    The file is written as UTF-8 with BOM (``utf-8-sig``) and LF line endings,
    with :data:`HEADER` as the first row and one row per transaction, in the
    order given.  The destination directory must already exist.

    Args:
        transactions: Transactions to write.
        path: Output file path.

    Returns:
        The number of data rows written (header excluded).

    Raises:
        bank_parser.errors.WriteError: If the output cannot be written or an
            amount is not canonical.
    """
    return _WRITER.write(transactions, Path(path))
