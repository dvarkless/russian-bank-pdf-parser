"""Alfa-Bank CSV adapter and row mapper."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from ..domain.models import (
    InputFormat,
    Money,
    OperationType,
    SourceLocation,
    Transaction,
)
from ..domain.raw import NormalizedDocument, NormalizedTable, RawRecord
from ..errors import (
    AmountParseError,
    DateParseError,
    MissingHeaderError,
    NormalizationError,
    ParseError,
)
from ..ports.adapter import BankAdapter
from ..ports.detection import Detection, DetectionContext
from ..ports.mapping import AmountParser, DateParser, RowMapper

__all__ = ["AlfaCsvAdapter", "AlfaCsvMapper"]


def _cell(record: RawRecord, index: int | None) -> str:
    """Return a record cell by resolved column index, or ``""`` when absent."""
    if index is None:
        return ""
    return record.cell(index)


class AlfaCsvMapper:
    """Map normalised Alfa-Bank CSV tables to canonical transactions.

    Columns are resolved by header name through
    :class:`~bank_parser.domain.raw.NormalizedTable.layout`, never by position.
    Alfa exports positive amounts plus an explicit ``type`` column, so the sign
    is derived from that column rather than from the amount: a ``Списание``
    amount becomes a negative :class:`~bank_parser.domain.models.Money` and a
    ``Пополнение`` amount a positive one, and
    :meth:`Transaction.from_money` stores only the absolute value.

    The operation date comes from ``operationDate`` and falls back to
    ``transactionDate`` only when ``operationDate`` is blank; the processing
    date is never used in place of an available operation date.  ``status`` is
    never consulted: ``Выполнен``, ``В обработке`` and blank rows are all
    mapped.
    """

    OPERATION_DATE_HEADER = "operationDate"
    TRANSACTION_DATE_HEADER = "transactionDate"
    MERCHANT_HEADER = "merchant"
    AMOUNT_HEADER = "amount"
    CURRENCY_HEADER = "currency"
    CATEGORY_HEADER = "category"
    COMMENT_HEADER = "comment"
    TYPE_HEADER = "type"
    STATUS_HEADER = "status"

    DEBIT_TYPE = "Списание"
    CREDIT_TYPE = "Пополнение"
    TYPE_EXPECTED = "Списание or Пополнение"

    REQUIRED_HEADERS: ClassVar[tuple[str, ...]] = (
        OPERATION_DATE_HEADER,
        MERCHANT_HEADER,
        AMOUNT_HEADER,
        TYPE_HEADER,
    )

    def __init__(
        self, date_parser: DateParser, amount_parser: AmountParser
    ) -> None:
        """Initialise the mapper with its injected value parsers.

        Args:
            date_parser: Context-free parser for operation dates.
            amount_parser: Context-free parser for signed operation amounts.
        """
        self._date_parser = date_parser
        self._amount_parser = amount_parser

    def map(self, document: NormalizedDocument) -> list[Transaction]:
        """Map a normalised Alfa CSV table to transactions.

        Every record yields exactly one transaction, in input order.  The
        normaliser already drops all-empty rows; a defensive check repeats that
        rule so a hand-built table cannot produce empty transactions.

        Args:
            document: Normalised table produced by a ``TableNormalizer``.

        Returns:
            Transactions in the same order as the source records.

        Raises:
            NormalizationError: If *document* is not a ``NormalizedTable``.
            MissingHeaderError: If a required header is absent from the layout.
            DateParseError: If a record's operation date cannot be parsed.
            AmountParseError: If a record's amount cannot be parsed or cannot
                be represented as a two-decimal ``Money`` value.
            ParseError: If a record's ``type`` is missing or unknown.
        """
        if not isinstance(document, NormalizedTable):
            raise NormalizationError(
                "AlfaCsvMapper expects a NormalizedTable, got "
                f"{type(document).__name__}"
            )

        layout = document.layout
        missing = [
            header
            for header in self.REQUIRED_HEADERS
            if layout.index_of(header) is None
        ]
        if missing:
            raise MissingHeaderError(
                location=self._table_location(document),
                missing=missing,
                found=layout.headers,
            )

        index_operation_date = layout.index_of(self.OPERATION_DATE_HEADER)
        index_transaction_date = layout.index_of(
            self.TRANSACTION_DATE_HEADER
        )
        index_merchant = layout.index_of(self.MERCHANT_HEADER)
        index_amount = layout.index_of(self.AMOUNT_HEADER)
        index_currency = layout.index_of(self.CURRENCY_HEADER)
        index_category = layout.index_of(self.CATEGORY_HEADER)
        index_comment = layout.index_of(self.COMMENT_HEADER)
        index_type = layout.index_of(self.TYPE_HEADER)

        transactions: list[Transaction] = []
        for record in document.records:
            if not any(cell.strip() for cell in record.cells):
                continue  # Defensive: the normaliser already drops these.
            transactions.append(
                self._map_record(
                    record,
                    index_operation_date=index_operation_date,
                    index_transaction_date=index_transaction_date,
                    index_merchant=index_merchant,
                    index_amount=index_amount,
                    index_currency=index_currency,
                    index_category=index_category,
                    index_comment=index_comment,
                    index_type=index_type,
                )
            )
        return transactions

    @staticmethod
    def _table_location(document: NormalizedTable) -> SourceLocation:
        """Return a location for a table-level error.

        A normalised table carries no document source, so the first record's
        location is used when available; otherwise a placeholder path keeps the
        error message actionable.
        """
        if document.records:
            return document.records[0].location
        return SourceLocation(path=Path("<table>"), format=InputFormat.CSV)

    def _map_record(
        self,
        record: RawRecord,
        *,
        index_operation_date: int | None,
        index_transaction_date: int | None,
        index_merchant: int | None,
        index_amount: int | None,
        index_currency: int | None,
        index_category: int | None,
        index_comment: int | None,
        index_type: int | None,
    ) -> Transaction:
        """Map one normalised record to a transaction.

        Args:
            record: Raw record with cells and its source location.
            index_operation_date: Column index of ``operationDate``.
            index_transaction_date: Column index of ``transactionDate`` or
                ``None``.
            index_merchant: Column index of ``merchant``.
            index_amount: Column index of ``amount``.
            index_currency: Column index of ``currency`` or ``None``.
            index_category: Column index of ``category`` or ``None``.
            index_comment: Column index of ``comment`` or ``None``.
            index_type: Column index of ``type``.

        Returns:
            The canonical transaction.

        Raises:
            DateParseError: If the operation date cannot be parsed.
            AmountParseError: If the amount cannot be parsed or represented.
            ParseError: If the ``type`` value is missing or unknown.
        """
        raw_operation_date = _cell(record, index_operation_date)
        raw_transaction_date = _cell(record, index_transaction_date)
        raw_date = (
            raw_operation_date
            if raw_operation_date.strip()
            else raw_transaction_date
        )

        try:
            operation_date = self._date_parser.parse(raw_date)
        except (TypeError, ValueError) as exc:
            raise DateParseError(
                location=record.location, raw_value=raw_date
            ) from exc

        raw_amount = _cell(record, index_amount)
        try:
            amount = self._amount_parser.parse(raw_amount)
        except (TypeError, ValueError) as exc:
            raise AmountParseError(
                location=record.location, raw_value=raw_amount
            ) from exc

        raw_type = _cell(record, index_type)
        type_name = raw_type.strip()
        if type_name == self.DEBIT_TYPE:
            operation_type = OperationType.DEBIT
        elif type_name == self.CREDIT_TYPE:
            operation_type = OperationType.CREDIT
        else:
            raise ParseError(
                location=record.location,
                field="type",
                raw_value=raw_type,
                expected=self.TYPE_EXPECTED,
            )

        signed_amount = (
            -abs(amount)
            if operation_type is OperationType.DEBIT
            else abs(amount)
        )
        currency = _cell(record, index_currency).strip()
        try:
            money = Money(amount=signed_amount, currency=currency)
        except ValueError as exc:
            raise AmountParseError(
                location=record.location,
                raw_value=raw_amount,
                expected="a decimal amount with at most 2 decimal places",
            ) from exc

        # The explicit ``type`` column is authoritative, including for a
        # hypothetical zero-amount row where the Money sign would be ambiguous.
        return Transaction(
            date=operation_date,
            merchant=_cell(record, index_merchant).strip(),
            amount=money.absolute,
            currency=money.currency,
            category=_cell(record, index_category).strip(),
            operation_type=operation_type,
            comment=_cell(record, index_comment).strip(),
            location=record.location,
        )


class AlfaCsvAdapter(BankAdapter):
    """Bank adapter for the Alfa-Bank 16-column English CSV export.

    The fixture (``Альфа.CSV``) is comma-delimited UTF-8 with a BOM.  Detection
    is filename-first; the distinctive English header is a secondary signal at
    confidence 70, so a neutral filename still resolves to Alfa while Russian
    17-column statements are left to the T-Bank/Sber tie.
    """

    name = "alfa"
    aliases = ("alfa", "alpha", "альфа", "альфа-банк")
    formats = frozenset({InputFormat.CSV})
    required_headers = (
        "operationDate",
        "merchant",
        "amount",
        "type",
    )

    FILENAME_TOKENS: ClassVar[frozenset[str]] = frozenset(
        {"alfa", "alpha", "альфа", "альфабанк", "alfabank"}
    )
    HEADER_SIGNATURE: ClassVar[tuple[str, ...]] = (
        "operationDate",
        "merchant",
        "amount",
        "type",
    )
    FILENAME_CONFIDENCE: ClassVar[int] = 90
    HEADER_CONFIDENCE: ClassVar[int] = 70

    @classmethod
    def probe(cls, ctx: DetectionContext) -> Detection | None:
        """Return a confidence-scored Alfa-Bank detection for *ctx*.

        Filename markers (``alfa``/``alpha``/``альфа``/``alfabank``) score 90.
        The distinctive English header scores 70.

        Args:
            ctx: Cached detection context with lazy filename/header signals.

        Returns:
            The detection, or ``None`` when no Alfa signal matches.
        """
        matched_tokens = sorted(cls.FILENAME_TOKENS & ctx.filename_tokens)
        if matched_tokens:
            return Detection(
                cls.name,
                cls.FILENAME_CONFIDENCE,
                f"filename contains {matched_tokens[0]!r}",
            )

        header = ctx.csv_header()
        if header:
            names = {cell.lstrip("\ufeff").strip() for cell in header}
            if all(marker in names for marker in cls.HEADER_SIGNATURE):
                return Detection(
                    cls.name,
                    cls.HEADER_CONFIDENCE,
                    "CSV header matches the Alfa English schema",
                )
        return None

    def create_mapper(self) -> RowMapper:
        """Return an Alfa CSV mapper wired with the injected parsers."""
        return AlfaCsvMapper(
            self._deps.date_parser, self._deps.amount_parser
        )
