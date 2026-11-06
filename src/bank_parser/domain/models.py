"""Domain value objects for the bank statement parser."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
from pathlib import Path

__all__ = [
    "InputFormat",
    "Money",
    "OperationType",
    "SourceLocation",
    "Transaction",
]


class InputFormat(str, Enum):
    """Supported statement input formats."""

    CSV = "csv"
    PDF = "pdf"


class OperationType(str, Enum):
    """Sign of a transaction in the canonical Russian wording."""

    DEBIT = "Списание"
    CREDIT = "Пополнение"

    @classmethod
    def from_signed_amount(cls, amount: Decimal) -> OperationType:
        """Derive the operation type from a signed amount.

        Args:
            amount: Signed amount; positive is a credit, zero or negative debit.

        Returns:
            ``OperationType.CREDIT`` for positive amounts, otherwise
            ``OperationType.DEBIT``.
        """
        return cls.CREDIT if amount > 0 else cls.DEBIT


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Where a raw value came from, for diagnostics and error messages.

    Attributes:
        path: Input file path.
        format: Input format of the file.
        page: 1-based PDF page, when the source is a PDF.
        data_row: 1-based logical record in the statement.
        physical_row: 1-based row/line in the extracted document.
    """

    path: Path
    format: InputFormat
    page: int | None = None
    data_row: int | None = None
    physical_row: int | None = None

    def __post_init__(self) -> None:
        for name in ("page", "data_row", "physical_row"):
            value = getattr(self, name)
            if value is not None and value < 1:
                raise ValueError(
                    f"SourceLocation.{name} must be >= 1, got {value}"
                )

    def describe(self) -> str:
        """Return a stable, human-readable location string.

        Returns:
            A string such as ``"data/input/T-Банк.csv data row 45"`` or
            ``"data/input/Ozon.pdf page 3, data row 12"``.
        """
        tags: list[str] = []
        if self.page is not None:
            tags.append(f"page {self.page}")
        if self.data_row is not None:
            tags.append(f"data row {self.data_row}")
        if self.physical_row is not None:
            tags.append(f"physical row {self.physical_row}")
        if not tags:
            return str(self.path)
        return f"{self.path} {', '.join(tags)}"


@dataclass(frozen=True, slots=True)
class Money:
    """A signed amount together with its source currency code.

    Attributes:
        amount: Signed amount; negative is a debit, positive a credit, and
            zero is treated as a debit.
        currency: Currency code exactly as reported by the source; may be
            empty when the source has no currency at all.
    """

    amount: Decimal
    currency: str

    def __post_init__(self) -> None:
        if not isinstance(self.amount, Decimal):
            raise ValueError(
                "Money.amount must be a decimal.Decimal, got "
                f"{type(self.amount).__name__}"
            )
        if not self.amount.is_finite():
            raise ValueError(
                f"Money.amount must be finite, got {self.amount!r}"
            )
        exponent = self.amount.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -2:
            raise ValueError(
                "Money.amount must have at most 2 decimal places, got "
                f"{self.amount!r}"
            )
        if not isinstance(self.currency, str):
            raise ValueError(
                "Money.currency must be a str, got "
                f"{type(self.currency).__name__}"
            )

    @property
    def absolute(self) -> Decimal:
        """Return the absolute (unsigned) amount."""
        return abs(self.amount)

    @property
    def is_credit(self) -> bool:
        """Return True when the signed amount is positive."""
        return self.amount > 0

    @property
    def operation_type(self) -> OperationType:
        """Return the canonical operation type derived from the sign."""
        return OperationType.from_signed_amount(self.amount)

    def __neg__(self) -> Money:
        """Return a copy of this value with the sign flipped."""
        return Money(amount=-self.amount, currency=self.currency)


@dataclass(frozen=True, slots=True)
class Transaction:
    """One canonical transaction row.

    The field order matches the v1 model so existing callers keep working;
    ``location`` is appended with a default.

    Attributes:
        date: Operation date.
        merchant: Merchant or operation description.
        amount: Absolute amount with at most 2 decimal places.
        currency: Source currency code, e.g. ``"RUB"`` or ``"RUR"``.
        category: Category assigned by the bank.
        operation_type: Debit or credit derived from the signed source amount.
        comment: Free-form source comment; may be empty.
        location: Diagnostics-only origin; never written to the output.
    """

    date: date
    merchant: str
    amount: Decimal
    currency: str
    category: str
    operation_type: OperationType
    comment: str
    location: SourceLocation | None = None

    @classmethod
    def from_money(
        cls,
        *,
        date: date,
        merchant: str,
        money: Money,
        category: str,
        comment: str = "",
        location: SourceLocation | None = None,
    ) -> Transaction:
        """Build a transaction from a signed :class:`Money` value.

        Args:
            date: Operation date.
            merchant: Merchant or operation description.
            money: Signed amount and currency; the sign becomes the operation
                type and only the absolute amount is stored.
            category: Category assigned by the bank.
            comment: Free-form source comment.
            location: Diagnostics-only origin.

        Returns:
            A transaction with an absolute ``amount`` and an ``OperationType``.
        """
        return cls(
            date=date,
            merchant=merchant,
            amount=money.absolute,
            currency=money.currency,
            category=category,
            operation_type=money.operation_type,
            comment=comment,
            location=location,
        )
