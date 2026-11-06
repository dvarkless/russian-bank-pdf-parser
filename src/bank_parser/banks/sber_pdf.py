"""Sber PDF adapter and line-oriented transaction mapper.

``data/input/Сбер.pdf`` is a text-based statement: pdfplumber reports no
tables, and each operation spans two consecutive text lines (operation header
followed by the description).  This module implements the state machine
described in ``docs/architecture.md`` §10.5 and reuses the shared domain date
and amount parsers.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import ClassVar

from ..domain.models import InputFormat, Money, SourceLocation, Transaction
from ..domain.raw import NormalizedDocument, NormalizedText, RawLine
from ..errors import (
    AmountParseError,
    DateParseError,
    NormalizationError,
    ParseError,
)
from ..ports.adapter import BankAdapter
from ..ports.detection import Detection, DetectionContext
from ..ports.extraction import PdfExtractor
from ..ports.mapping import AmountParser, DateParser, RowMapper
from ..ports.pipeline import InputNormalizer

__all__ = ["SberPdfAdapter", "SberPdfMapper"]

#: Currency of every row in the Sber PDF statement; the adapter declares it.
STATEMENT_CURRENCY = "RUR"

#: Operation header: date, time, category, signed amount, balance.
_HEADER_PATTERN = re.compile(
    r"^(?P<date>\d{2}\.\d{2}\.\d{4})\s+(?P<time>\d{2}:\d{2})\s+"
    r"(?P<category>.+?)\s+(?P<amount>[+-]?\s?[\d\s\u00a0]+,\d{2})\s+"
    r"(?P<balance>[\d\s\u00a0]+,\d{2})$"
)

#: Description line: processing date, 6-digit authorisation code, merchant.
_DESCRIPTION_PATTERN = re.compile(
    r"^(?P<processing_date>\d{2}\.\d{2}\.\d{4})\s+"
    r"(?P<auth>\d{6})\s+(?P<merchant>.+)$"
)

#: Trailing "... . Операция по карте/счету ****dddd" suffix.
_DESCRIPTION_SUFFIX = re.compile(
    r"\s*\.{1,2}\s*Операция по (?:карте|счету)"
    r"(?:\s*\*{4}\d{4})?\s*$"
)

#: A description line that has no merchant text after the auth code.
_DESCRIPTION_PREFIX = re.compile(r"^\d{2}\.\d{2}\.\d{4}\s+\d{6}(?:\s|$)")

#: Characters removed from the end of a merchant (dots and spaces only).
_TRAILING_MERCHANT_CHARS = " ."


@dataclass(frozen=True, slots=True)
class _PendingOperation:
    """Operation header waiting for its description line.

    Attributes:
        date: Operation date from the header (not the processing date).
        category: Category text from the header, trimmed.
        money: Signed amount and statement currency.
        location: Source location of the header line.
    """

    date: date
    category: str
    money: Money
    location: SourceLocation


class SberPdfMapper:
    """Map normalised Sber PDF text to canonical transactions.

    Implements the line state machine ``AWAIT_HEADER -> AWAIT_DESCRIPTION ->
    AWAIT_HEADER``: an operation header opens a pending transaction and the
    immediately following description line supplies the merchant.  Report
    headers, page furniture, continuation markers and legal text that match
    neither pattern are ignored.  Page/line order is preserved and the
    processing date is ignored in favour of the operation date.
    """

    def __init__(
        self, date_parser: DateParser, amount_parser: AmountParser
    ) -> None:
        """Initialise the mapper with its injected value parsers.

        Args:
            date_parser: Context-free parser for operation dates.
            amount_parser: Context-free parser for signed amounts.
        """
        self._date_parser = date_parser
        self._amount_parser = amount_parser

    def map(self, document: NormalizedDocument) -> list[Transaction]:
        """Map normalised Sber PDF text lines to transactions.

        Every operation header plus its description line yields one
        transaction, in page/line order.  A header followed by another header
        (or by end of document) has no description and raises a
        :class:`~bank_parser.errors.ParseError`; so does a description without
        a usable merchant.

        Args:
            document: Normalised text produced by a ``TextNormalizer``.

        Returns:
            Transactions in page/line order.

        Raises:
            NormalizationError: If *document* is not a ``NormalizedText``.
            ParseError: If an operation is missing its description or merchant.
            DateParseError: If a header operation date cannot be parsed.
            AmountParseError: If a header amount cannot be parsed.
        """
        if not isinstance(document, NormalizedText):
            raise NormalizationError(
                "SberPdfMapper expects a NormalizedText, got "
                f"{type(document).__name__}"
            )

        transactions: list[Transaction] = []
        pending: _PendingOperation | None = None
        for raw_line in document.lines:
            header = _HEADER_PATTERN.match(raw_line.text)

            if pending is None:
                if header is not None:
                    pending = self._parse_header(document, raw_line, header)
                continue

            if header is not None:
                raise ParseError(
                    location=pending.location,
                    field="description",
                    raw_value=raw_line.text,
                    expected="a description line after the operation header",
                )

            description = _DESCRIPTION_PATTERN.match(raw_line.text)
            if description is not None:
                transactions.append(
                    self._build_transaction(
                        document,
                        raw_line,
                        pending,
                        description,
                        data_row=len(transactions) + 1,
                    )
                )
                pending = None
                continue

            if _DESCRIPTION_PREFIX.match(raw_line.text):
                raise ParseError(
                    location=self._line_location(document, raw_line),
                    field="merchant",
                    raw_value=raw_line.text,
                    expected="a non-empty merchant description",
                )
            # Any other line is page furniture or a continuation marker
            # (e.g. ``****5838``): keep waiting for the description line.

        if pending is not None:
            raise ParseError(
                location=pending.location,
                field="description",
                raw_value="",
                expected="a description line after the operation header",
            )
        return transactions

    def _parse_header(
        self,
        document: NormalizedText,
        raw_line: RawLine,
        match: re.Match[str],
    ) -> _PendingOperation:
        """Parse an operation header line into a pending operation.

        Args:
            document: Normalised text owning the line, for its source.
            raw_line: The header line.
            match: Successful match of the operation header pattern.

        Returns:
            The pending operation awaiting its description line.

        Raises:
            DateParseError: If the operation date cannot be parsed.
            AmountParseError: If the amount cannot be parsed or represented.
            ParseError: If the balance text cannot be parsed.
        """
        location = self._line_location(document, raw_line)

        raw_date = match.group("date")
        try:
            operation_date = self._date_parser.parse(raw_date)
        except (TypeError, ValueError) as exc:
            raise DateParseError(
                location=location, raw_value=raw_date
            ) from exc

        raw_amount = match.group("amount")
        try:
            parsed_amount = self._amount_parser.parse(raw_amount)
        except (TypeError, ValueError) as exc:
            raise AmountParseError(
                location=location, raw_value=raw_amount
            ) from exc

        signed_amount = (
            abs(parsed_amount)
            if raw_amount.lstrip().startswith("+")
            else -abs(parsed_amount)
        )
        try:
            money = Money(amount=signed_amount, currency=STATEMENT_CURRENCY)
        except ValueError as exc:
            raise AmountParseError(
                location=location,
                raw_value=raw_amount,
                expected="a decimal amount with at most 2 decimal places",
            ) from exc

        # The balance is parsed for sanity only; it never reaches the output.
        raw_balance = match.group("balance")
        try:
            self._amount_parser.parse(raw_balance)
        except (TypeError, ValueError) as exc:
            raise ParseError(
                location=location,
                field="balance",
                raw_value=raw_balance,
                expected="a decimal balance",
            ) from exc

        return _PendingOperation(
            date=operation_date,
            category=match.group("category").strip(),
            money=money,
            location=location,
        )

    def _build_transaction(
        self,
        document: NormalizedText,
        raw_line: RawLine,
        pending: _PendingOperation,
        match: re.Match[str],
        *,
        data_row: int,
    ) -> Transaction:
        """Build a transaction from a pending header and its description.

        Args:
            document: Normalised text owning the line, for its source.
            raw_line: The description line.
            pending: Operation parsed from the preceding header line.
            match: Successful match of the description pattern.
            data_row: 1-based transaction number in the output.

        Returns:
            The canonical transaction.

        Raises:
            ParseError: If the merchant is empty after suffix removal.
        """
        remainder = match.group("merchant")
        merchant = _DESCRIPTION_SUFFIX.sub("", remainder)
        merchant = merchant.strip().rstrip(_TRAILING_MERCHANT_CHARS)
        if not merchant:
            raise ParseError(
                location=self._line_location(document, raw_line),
                field="merchant",
                raw_value=remainder,
                expected="a non-empty merchant description",
            )

        location = SourceLocation(
            path=document.source.path,
            format=document.source.format,
            page=raw_line.page,
            data_row=data_row,
            physical_row=raw_line.line,
        )
        return Transaction.from_money(
            date=pending.date,
            merchant=merchant,
            money=pending.money,
            category=pending.category,
            comment="",
            location=location,
        )

    @staticmethod
    def _line_location(
        document: NormalizedText, raw_line: RawLine
    ) -> SourceLocation:
        """Return the location of *raw_line* within *document*."""
        return SourceLocation(
            path=document.source.path,
            format=document.source.format,
            page=raw_line.page,
            physical_row=raw_line.line,
        )


class SberPdfAdapter(BankAdapter):
    """Bank adapter for the Sber PDF statement.

    Detection is filename-first (90), with the first-page body signature
    ``Выписка по платёжному счёту`` + ``СберБанк`` as a 85 fallback.  The
    Sber CSV and Sber PDF adapters share aliases; the registry's format-aware
    alias map disambiguates ``.csv`` from ``.pdf`` inputs.
    """

    name = "sber-pdf"
    aliases = ("sber-pdf", "sber", "сбер", "сбербанк")
    formats = frozenset({InputFormat.PDF})
    statement_currency = STATEMENT_CURRENCY
    required_headers = ()

    FILENAME_TOKENS: ClassVar[frozenset[str]] = frozenset(
        {"sber", "сбер", "sberbank", "сбербанк"}
    )
    BODY_SIGNATURE: ClassVar[tuple[str, ...]] = (
        "Выписка по платёжному счёту",
        "СберБанк",
    )
    FILENAME_CONFIDENCE: ClassVar[int] = 90
    BODY_CONFIDENCE: ClassVar[int] = 85

    @classmethod
    def probe(cls, ctx: DetectionContext) -> Detection | None:
        """Return a confidence-scored Sber PDF detection for *ctx*.

        A filename marker scores 90.  Otherwise the first-page text must
        contain the whole body signature, which scores 85.

        Args:
            ctx: Cached detection context with lazy filename/text signals.

        Returns:
            The detection, or ``None`` when no Sber PDF signal matches.
        """
        matched_tokens = sorted(cls.FILENAME_TOKENS & ctx.filename_tokens)
        if matched_tokens:
            return Detection(
                cls.name,
                cls.FILENAME_CONFIDENCE,
                f"filename contains {matched_tokens[0]!r}",
            )

        first_page = ctx.pdf_first_page_text()
        if first_page and all(
            marker in first_page for marker in cls.BODY_SIGNATURE
        ):
            return Detection(
                cls.name,
                cls.BODY_CONFIDENCE,
                "first page contains the Sber statement body signature",
            )
        return None

    def create_extractor(self) -> PdfExtractor:
        """Return the pdfplumber text extractor for this statement."""
        # Imported lazily: the adapters module owns the pdfplumber boundary and
        # must not be loaded from the package import path.
        from ..adapters.pdf_extractors import PdfPlumberTextExtractor

        return PdfPlumberTextExtractor()

    def create_normalizer(self) -> InputNormalizer:
        """Return the text normaliser used for PDF statements."""
        from ..adapters.normalizers import TextNormalizer

        return TextNormalizer()

    def create_mapper(self) -> RowMapper:
        """Return a Sber PDF mapper wired with the injected parsers."""
        return SberPdfMapper(
            self._deps.date_parser, self._deps.amount_parser
        )
