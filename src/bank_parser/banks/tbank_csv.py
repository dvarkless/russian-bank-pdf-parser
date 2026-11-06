"""T-Bank CSV adapter and row mapper."""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

from ..domain.models import InputFormat, Money, SourceLocation, Transaction
from ..domain.raw import NormalizedDocument, NormalizedTable, RawRecord
from ..errors import (
    AmountParseError,
    DateParseError,
    MissingHeaderError,
    NormalizationError,
)
from ..ports.adapter import BankAdapter
from ..ports.detection import Detection, DetectionContext
from ..ports.mapping import AmountParser, DateParser, RowMapper

__all__ = ["TbankCsvAdapter", "TbankCsvMapper"]


def _cell(record: RawRecord, index: int | None) -> str:
    """Return a record cell by resolved column index, or ``""`` when absent."""
    if index is None:
        return ""
    return record.cell(index)


class TbankCsvMapper:
    """Map normalised T-Bank CSV tables to canonical transactions.

    Columns are resolved by header name through
    :class:`~bank_parser.domain.raw.NormalizedTable.layout`, never by position,
    so reordered or extra columns do not change the result.  The same mapping
    is reused for the Sber CSV export, whose header is identical.

    Date and amount parsing is delegated to the injected pure parsers.  Parser
    failures are re-raised as location-aware
    :class:`~bank_parser.errors.DateParseError` /
    :class:`~bank_parser.errors.AmountParseError`; money is built as a signed
    :class:`~bank_parser.domain.models.Money` and converted with
    :meth:`Transaction.from_money`, so the operation type follows the sign.
    """

    DATE_HEADER = "Дата операции"
    AMOUNT_HEADER = "Сумма операции"
    DESCRIPTION_HEADER = "Описание"
    CURRENCY_HEADER = "Валюта операции"
    ACCOUNT_CURRENCY_HEADER = "Валюта счёта"
    CATEGORY_HEADER = "Категория по-умолчанию"
    USER_CATEGORY_HEADER = "Ваша категория"
    COMMENT_HEADER = "Сообщение"

    REQUIRED_HEADERS: ClassVar[tuple[str, ...]] = (
        DATE_HEADER,
        AMOUNT_HEADER,
        DESCRIPTION_HEADER,
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
        """Map a normalised T-Bank table to transactions.

        Every record yields exactly one transaction, in input order.  The
        normaliser already drops all-empty rows; a defensive check repeats
        that rule so a hand-built table cannot produce empty transactions.

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
        """
        if not isinstance(document, NormalizedTable):
            raise NormalizationError(
                "TbankCsvMapper expects a NormalizedTable, got "
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

        index_date = layout.index_of(self.DATE_HEADER)
        index_amount = layout.index_of(self.AMOUNT_HEADER)
        index_currency = layout.index_of(self.CURRENCY_HEADER)
        index_account_currency = layout.index_of(self.ACCOUNT_CURRENCY_HEADER)
        index_category = layout.index_of(self.CATEGORY_HEADER)
        index_user_category = layout.index_of(self.USER_CATEGORY_HEADER)
        index_message = layout.index_of(self.COMMENT_HEADER)
        index_description = layout.index_of(self.DESCRIPTION_HEADER)

        transactions: list[Transaction] = []
        for record in document.records:
            if not any(cell.strip() for cell in record.cells):
                continue  # Defensive: the normaliser already drops these.
            transactions.append(
                self._map_record(
                    record,
                    index_date=index_date,
                    index_amount=index_amount,
                    index_description=index_description,
                    index_currency=index_currency,
                    index_account_currency=index_account_currency,
                    index_category=index_category,
                    index_user_category=index_user_category,
                    index_message=index_message,
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
        index_date: int | None,
        index_amount: int | None,
        index_description: int | None,
        index_currency: int | None,
        index_account_currency: int | None,
        index_category: int | None,
        index_user_category: int | None,
        index_message: int | None,
    ) -> Transaction:
        """Map one normalised record to a transaction.

        Args:
            record: Raw record with cells and its source location.
            index_date: Column index of ``Дата операции``.
            index_amount: Column index of ``Сумма операции``.
            index_description: Column index of ``Описание``.
            index_currency: Column index of ``Валюта операции`` or ``None``.
            index_account_currency: Column index of ``Валюта счёта`` or
                ``None``.
            index_category: Column index of ``Категория по-умолчанию`` or
                ``None``.
            index_user_category: Column index of ``Ваша категория`` or
                ``None``.
            index_message: Column index of ``Сообщение`` or ``None``.

        Returns:
            The canonical transaction.

        Raises:
            DateParseError: If the operation date cannot be parsed.
            AmountParseError: If the amount cannot be parsed or represented.
        """
        raw_date = _cell(record, index_date)
        raw_amount = _cell(record, index_amount)

        try:
            operation_date = self._date_parser.parse(raw_date)
        except (TypeError, ValueError) as exc:
            raise DateParseError(
                location=record.location, raw_value=raw_date
            ) from exc

        try:
            signed_amount = self._amount_parser.parse(raw_amount)
        except (TypeError, ValueError) as exc:
            raise AmountParseError(
                location=record.location, raw_value=raw_amount
            ) from exc

        currency = _cell(record, index_currency).strip()
        if not currency:
            currency = _cell(record, index_account_currency).strip()

        try:
            money = Money(amount=signed_amount, currency=currency)
        except ValueError as exc:
            raise AmountParseError(
                location=record.location,
                raw_value=raw_amount,
                expected="a decimal amount with at most 2 decimal places",
            ) from exc

        category = _cell(record, index_category).strip()
        if not category:
            category = _cell(record, index_user_category).strip()

        return Transaction.from_money(
            date=operation_date,
            merchant=_cell(record, index_description).strip(),
            money=money,
            category=category,
            comment=_cell(record, index_message).strip(),
            location=record.location,
        )


class TbankCsvAdapter(BankAdapter):
    """Bank adapter for the T-Bank 17-column CSV export.

    The T-Bank fixture (``T-Банк.csv``) is semicolon-delimited UTF-8 with a
    header shared by the Sber CSV export.  Detection is therefore
    filename-first; the generic header signature only scores 60 so the registry
    can report a tie instead of silently guessing.
    """

    name = "tbank"
    aliases = ("tbank", "t-bank", "т-банк", "т банк")
    formats = frozenset({InputFormat.CSV})
    required_headers = ("Дата операции", "Сумма операции", "Описание")

    FILENAME_TOKENS: ClassVar[frozenset[str]] = frozenset(
        {"tbank", "тбанк", "tбанк"}
    )
    HEADER_SIGNATURE: ClassVar[tuple[str, ...]] = (
        "Номер карты",
        "Дата операции",
        "Сумма операции",
        "Описание",
    )
    FILENAME_CONFIDENCE: ClassVar[int] = 90
    HEADER_CONFIDENCE: ClassVar[int] = 60

    @classmethod
    def probe(cls, ctx: DetectionContext) -> Detection | None:
        """Return a confidence-scored T-Bank detection for *ctx*.

        Filename markers (``tbank``/``t-bank``, including the compacted
        mixed-script token produced for ``T-Банк``) score 90.  The generic
        17-column Russian CSV header scores 60 because it is shared with the
        Sber CSV export.

        Args:
            ctx: Cached detection context with lazy filename/header signals.

        Returns:
            The detection, or ``None`` when no T-Bank signal matches.
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
            names = {
                cell.lstrip("\ufeff").strip()
                for cell in header
            }
            if all(marker in names for marker in cls.HEADER_SIGNATURE):
                return Detection(
                    cls.name,
                    cls.HEADER_CONFIDENCE,
                    "CSV header matches the generic 17-column Russian schema",
                )
        return None

    def create_mapper(self) -> RowMapper:
        """Return a T-Bank CSV mapper wired with the injected parsers."""
        return TbankCsvMapper(self._deps.date_parser, self._deps.amount_parser)
