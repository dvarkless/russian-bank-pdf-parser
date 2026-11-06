"""Canonical CSV writer: UTF-8 with BOM, LF, 8 fields per row."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import Iterable

from .models import Transaction

HEADER: list[str] = [
    "date",
    "merchant",
    "amount",
    "currency",
    "category",
    "type",
    "comment",
    "",
]
"""Canonical header row; the last field is an empty placeholder column."""

_DATE_FORMAT = "%d/%m/%Y"
_TWO_PLACES = Decimal("0.01")


def _format_amount(amount: Decimal) -> str:
    """Format *amount* as an absolute value with exactly two decimal places.

    ``Decimal`` arithmetic is used so that no binary floating point error can
    leak into the output.  The separator is always ``.``.
    """
    if not isinstance(amount, Decimal):
        amount = Decimal(str(amount))
    return format(abs(amount).quantize(_TWO_PLACES), "f")


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
    """
    target = Path(path)
    count = 0
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(HEADER)
        for transaction in transactions:
            writer.writerow(
                [
                    transaction.date.strftime(_DATE_FORMAT),
                    transaction.merchant,
                    _format_amount(transaction.amount),
                    transaction.currency,
                    transaction.category,
                    transaction.operation_type,
                    transaction.comment,
                    "",
                ]
            )
            count += 1
    return count
