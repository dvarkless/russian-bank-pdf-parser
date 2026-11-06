"""Canonical CSV writer: UTF-8 with BOM, LF, eight fields per row."""

from __future__ import annotations

import csv
from collections.abc import Iterable
from decimal import Decimal
from pathlib import Path

from ..domain.models import OperationType, Transaction
from ..errors import WriteError

__all__ = ["CanonicalCsvWriter"]


class CanonicalCsvWriter:
    """Write transactions in the canonical CSV format.

    Args:
        encoding: Output encoding; defaults to UTF-8 with BOM.
        line_terminator: CSV line terminator; defaults to LF.
    """

    HEADER: tuple[str, ...] = (
        "date",
        "merchant",
        "amount",
        "currency",
        "category",
        "type",
        "comment",
        "",
    )
    DATE_FORMAT: str = "%d/%m/%Y"
    TWO_PLACES: Decimal = Decimal("0.01")

    def __init__(
        self,
        *,
        encoding: str = "utf-8-sig",
        line_terminator: str = "\n",
    ) -> None:
        self._encoding = encoding
        self._line_terminator = line_terminator

    def write(
        self, transactions: Iterable[Transaction], path: Path
    ) -> int:
        """Write *transactions* to *path* and return the data-row count.

        Args:
            transactions: Transactions in canonical order.
            path: Destination path; its directory must already exist.

        Returns:
            Number of data rows written, header excluded.

        Raises:
            WriteError: When the amount cannot be formatted canonically or the
                file cannot be written.
        """
        target = Path(path)
        count = 0
        try:
            with target.open(
                "w", encoding=self._encoding, newline=""
            ) as handle:
                writer = csv.writer(
                    handle, lineterminator=self._line_terminator
                )
                writer.writerow(self.HEADER)
                for transaction in transactions:
                    writer.writerow(
                        [
                            transaction.date.strftime(self.DATE_FORMAT),
                            transaction.merchant,
                            self.format_amount(transaction.amount),
                            transaction.currency,
                            transaction.category,
                            self._operation_type_value(transaction),
                            transaction.comment,
                            "",
                        ]
                    )
                    count += 1
        except OSError as exc:
            raise WriteError(
                f"{target}: cannot write canonical CSV: {exc}"
            ) from exc
        return count

    @staticmethod
    def format_amount(amount: Decimal) -> str:
        """Format *amount* as an absolute value with exactly two decimals.

        Args:
            amount: Domain amount, already validated as a finite ``Decimal``
                with at most two decimal places.

        Returns:
            The canonical string using ``.`` as the decimal separator.

        Raises:
            WriteError: When *amount* is not a valid canonical amount.
        """
        if not isinstance(amount, Decimal):
            raise WriteError(
                "amount must be a Decimal, got "
                f"{type(amount).__name__}"
            )
        if not amount.is_finite():
            raise WriteError(f"amount must be finite, got {amount!r}")
        exponent = amount.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            raise WriteError(
                "amount must have at most 2 decimal places, got "
                f"{amount!r}"
            )
        return format(
            abs(amount).quantize(CanonicalCsvWriter.TWO_PLACES), "f"
        )

    @staticmethod
    def _operation_type_value(transaction: Transaction) -> str:
        """Return the canonical type string, using the enum value when present."""
        operation_type = transaction.operation_type
        if isinstance(operation_type, OperationType):
            return operation_type.value
        # Legacy callers may still construct a Transaction with a plain string;
        # the canonical writer keeps working until they migrate to the enum.
        return str(operation_type)
