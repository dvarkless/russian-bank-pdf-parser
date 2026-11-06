"""Postcondition validation for mapped canonical transactions."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from ..domain.models import OperationType, SourceLocation, Transaction
from ..domain.raw import NormalizedDocument
from ..errors import ValidationError

__all__ = ["DefaultStatementValidator"]

_TWO_PLACES_EXPONENT = -2


class DefaultStatementValidator:
    """Cross-check mapped transactions against domain invariants.

    The validator never changes values and never re-maps fields; it only raises
    :class:`~bank_parser.errors.ValidationError` when a mapper has produced a
    transaction that cannot be written canonically.
    """

    def validate(
        self,
        document: NormalizedDocument,
        transactions: Sequence[Transaction],
    ) -> None:
        """Validate every transaction produced for *document*.

        Args:
            document: Normalised input that produced the transactions.
            transactions: Mapped transactions in input order.

        Raises:
            ValidationError: When a transaction violates a domain invariant.
        """
        for position, transaction in enumerate(transactions, start=1):
            if not isinstance(transaction, Transaction):
                raise ValidationError(
                    f"{self._source_name(document)}: transaction {position} "
                    f"is not a Transaction, got "
                    f"{type(transaction).__name__}"
                )
            self._validate_transaction(
                transaction,
                position=position,
                document=document,
            )

    def _validate_transaction(
        self,
        transaction: Transaction,
        *,
        position: int,
        document: NormalizedDocument,
    ) -> None:
        """Validate one transaction or raise a located error."""
        prefix = self._location_prefix(transaction, document, position)

        if not isinstance(transaction.date, date):
            raise ValidationError(
                f"{prefix}: date must be datetime.date, got "
                f"{type(transaction.date).__name__}"
            )
        if not isinstance(transaction.merchant, str):
            raise ValidationError(f"{prefix}: merchant must be a str")
        if not isinstance(transaction.currency, str):
            raise ValidationError(f"{prefix}: currency must be a str")
        if not isinstance(transaction.category, str):
            raise ValidationError(f"{prefix}: category must be a str")
        if not isinstance(transaction.comment, str):
            raise ValidationError(f"{prefix}: comment must be a str")
        if not isinstance(transaction.operation_type, OperationType):
            raise ValidationError(
                f"{prefix}: operation_type must be OperationType, got "
                f"{type(transaction.operation_type).__name__}"
            )

        amount = transaction.amount
        if not isinstance(amount, Decimal):
            raise ValidationError(
                f"{prefix}: amount must be a Decimal, got "
                f"{type(amount).__name__}"
            )
        if not amount.is_finite():
            raise ValidationError(f"{prefix}: amount must be finite")
        if amount < 0:
            raise ValidationError(
                f"{prefix}: amount must be the absolute value, got {amount}"
            )
        exponent = amount.as_tuple().exponent
        if isinstance(exponent, int) and exponent < _TWO_PLACES_EXPONENT:
            raise ValidationError(
                f"{prefix}: amount has more than 2 decimal places: {amount}"
            )

    @staticmethod
    def _source_name(document: NormalizedDocument) -> str:
        """Return a readable source name for a document-level error."""
        source = getattr(document, "source", None)
        if isinstance(source, SourceLocation):
            return source.describe()
        return "input"

    @staticmethod
    def _location_prefix(
        transaction: Transaction,
        document: NormalizedDocument,
        position: int,
    ) -> str:
        """Return the best available location prefix for one transaction."""
        if transaction.location is not None:
            return transaction.location.describe()
        source = getattr(document, "source", None)
        if isinstance(source, SourceLocation):
            return f"{source.describe()} transaction {position}"
        return f"transaction {position}"
