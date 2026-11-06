"""Ozon PDF adapter, table predicate and purpose rule mapper.

``data/input/Ozon.pdf`` is table-based: pdfplumber returns one table per page
with five columns (operation date/time, document, purpose, amount RUB, amount
in account currency).  Page 1 has two header rows; the remaining pages have
none.  A :class:`TableNormalizer` record predicate keeps only real operation
rows, and :class:`OzonPdfMapper` applies the ordered purpose rules from
``docs/architecture.md`` §10.4.
"""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal
from typing import ClassVar

from ..domain.models import InputFormat, Money, Transaction
from ..domain.raw import (
    NormalizedDocument,
    NormalizedTable,
    RawRecord,
    RawRow,
)
from ..errors import (
    AmountParseError,
    DateParseError,
    NormalizationError,
    ParseError,
    ValidationError,
)
from ..ports.adapter import BankAdapter
from ..ports.detection import Detection, DetectionContext
from ..ports.extraction import PdfExtractor
from ..ports.mapping import AmountParser, DateParser, RowMapper
from ..ports.pipeline import InputNormalizer

__all__ = ["OzonPdfAdapter", "OzonPdfMapper"]

#: Currency of every Ozon record; the adapter declares it, the statement text
#: corroborates it (``Валюта: РОССИЙСКИЙ РУБЛЬ``).
STATEMENT_CURRENCY = "RUR"

#: First-cell pattern of a real operation row; first-match also skips headers.
_RECORD_DATE_PATTERN = re.compile(
    r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}$"
)

_PURPOSE_SBP = "через СБП"
_PURPOSE_RECIPIENT = "Получатель:"
_PURPOSE_OWN_FUNDS = "Перевод собственных средств"
_PURPOSE_OZON_PLATFORM = "Платформе Ozon"
_PURPOSE_GOODS = "Оплата товаров"
_PURPOSE_TIPS = "Чаевые по заказу"

_CATEGORY_SBP = "Перевод через СБП"
_CATEGORY_OWN_FUNDS = "Перевод собственных средств"
_CATEGORY_OZON_PLATFORM = "Оплата товаров/услуг на Платформе Ozon"
_CATEGORY_GOODS = "Оплата товаров"
_CATEGORY_TIPS = "Чаевые по заказу"

_OZON_PREMIUM = "(Ozon Premium)"
_WITHOUT_VAT_SUFFIX = ". Без НДС"


def is_record_row(row: RawRow) -> bool:
    """Return True when *row* is a real Ozon operation row.

    Args:
        row: Raw table row; header rows and repeated headers do not start with
            an operation timestamp.

    Returns:
        ``True`` when the first cell matches ``DD.MM.YYYY HH:MM:SS``.
    """
    first_cell = row.cells[0] if row.cells else ""
    return bool(_RECORD_DATE_PATTERN.match(first_cell))


def _normalize_purpose(raw: str) -> str:
    """Collapse CRLF/LF/whitespace runs in *raw* to single spaces."""
    return re.sub(r"\s+", " ", raw).strip()


class OzonPdfMapper:
    """Map normalised Ozon table records to canonical transactions.

    Each record has five columns: operation date/time, document, purpose,
    amount in RUB, and amount in the account currency.  The document column is
    ignored; the purpose is normalised and classified with ordered rules, and
    the signed amount drives :class:`~bank_parser.domain.models.Money` and the
    operation type.  Input order is preserved and no row is filtered.
    """

    DATE_COLUMN = 0
    PURPOSE_COLUMN = 2
    AMOUNT_COLUMN = 3
    ACCOUNT_AMOUNT_COLUMN = 4

    def __init__(
        self,
        date_parser: DateParser,
        amount_parser: AmountParser,
        *,
        currency: str = STATEMENT_CURRENCY,
    ) -> None:
        """Initialise the mapper with injected parsers and the currency code.

        Args:
            date_parser: Context-free parser for operation timestamps.
            amount_parser: Context-free parser for signed amounts.
            currency: Currency code applied to every transaction (``"RUR"``).
        """
        self._date_parser = date_parser
        self._amount_parser = amount_parser
        self._currency = currency

    def map(self, document: NormalizedDocument) -> list[Transaction]:
        """Map a normalised Ozon table to transactions.

        Every record yields exactly one transaction, in input order.  The
        date is the operation timestamp (time dropped); the amount comes from
        the RUB column (the account-currency column is cross-checked when
        present); the purpose is classified by the ordered rules.

        Args:
            document: Normalised table produced by the Ozon ``TableNormalizer``.

        Returns:
            Transactions in input order.

        Raises:
            NormalizationError: If *document* is not a ``NormalizedTable``.
            DateParseError: If a record's operation timestamp cannot be parsed.
            AmountParseError: If a record's amount cannot be parsed.
            ValidationError: If the two amount columns disagree.
            ParseError: If a purpose matches none of the supported rules.
        """
        if not isinstance(document, NormalizedTable):
            raise NormalizationError(
                "OzonPdfMapper expects a NormalizedTable, got "
                f"{type(document).__name__}"
            )

        transactions: list[Transaction] = []
        for record in document.records:
            raw_date = record.cell(self.DATE_COLUMN)
            try:
                operation_date = self._date_parser.parse(raw_date)
            except (TypeError, ValueError) as exc:
                raise DateParseError(
                    location=record.location, raw_value=raw_date
                ) from exc

            raw_amount = record.cell(self.AMOUNT_COLUMN)
            try:
                signed_amount = self._amount_parser.parse(raw_amount)
            except (TypeError, ValueError) as exc:
                raise AmountParseError(
                    location=record.location, raw_value=raw_amount
                ) from exc

            raw_account_amount = record.cell(
                self.ACCOUNT_AMOUNT_COLUMN
            ).strip()
            if raw_account_amount:
                try:
                    account_amount = self._amount_parser.parse(
                        raw_account_amount
                    )
                except (TypeError, ValueError) as exc:
                    raise AmountParseError(
                        location=record.location,
                        raw_value=raw_account_amount,
                    ) from exc
                if account_amount != signed_amount:
                    raise ValidationError(
                        f"{record.location.describe()}: amount columns "
                        f"disagree: {raw_amount!r} vs "
                        f"{raw_account_amount!r}"
                    )

            purpose = _normalize_purpose(
                record.cell(self.PURPOSE_COLUMN)
            )
            category, merchant = self._classify_purpose(
                purpose, record=record
            )

            try:
                money = Money(
                    amount=signed_amount, currency=self._currency
                )
            except ValueError as exc:
                raise AmountParseError(
                    location=record.location,
                    raw_value=raw_amount,
                    expected=(
                        "a decimal amount with at most 2 decimal places"
                    ),
                ) from exc

            transactions.append(
                Transaction.from_money(
                    date=operation_date,
                    merchant=merchant,
                    money=money,
                    category=category,
                    comment="",
                    location=record.location,
                )
            )
        return transactions

    def _classify_purpose(
        self, purpose: str, *, record: RawRecord
    ) -> tuple[str, str]:
        """Return ``(category, merchant)`` for a normalised purpose.

        Args:
            purpose: Purpose text with whitespace runs collapsed.
            record: Source record, used for the error location.

        Returns:
            The category and merchant for the first matching rule.

        Raises:
            ParseError: If no rule matches.
        """
        if _PURPOSE_SBP in purpose and _PURPOSE_RECIPIENT in purpose:
            return _CATEGORY_SBP, self._sbp_recipient(purpose)

        if _PURPOSE_OWN_FUNDS in purpose:
            return _CATEGORY_OWN_FUNDS, ""

        if _PURPOSE_OZON_PLATFORM in purpose:
            merchant = (
                _OZON_PREMIUM if _OZON_PREMIUM in purpose else ""
            )
            return _CATEGORY_OZON_PLATFORM, merchant

        if self._is_card_payment(purpose):
            return _CATEGORY_GOODS, self._card_merchant(purpose)

        if _PURPOSE_TIPS in purpose:
            return _CATEGORY_TIPS, ""

        raise ParseError(
            location=record.location,
            field="purpose",
            raw_value=purpose,
            expected="a supported Ozon purpose",
        )

    @staticmethod
    def _sbp_recipient(purpose: str) -> str:
        """Return the SBP recipient text after ``Получатель:``.

        The recipient ends at ``. Без НДС`` or at the end of the purpose.
        """
        after_recipient = purpose.split(_PURPOSE_RECIPIENT, 1)[1]
        return after_recipient.split(_WITHOUT_VAT_SUFFIX, 1)[0].strip()

    @staticmethod
    def _is_card_payment(purpose: str) -> bool:
        """Return True when *purpose* is a card-payment description."""
        return all(
            fragment in purpose
            for fragment in (
                _PURPOSE_GOODS,
                " по карте ",
                " в ",
                " дата ",
            )
        )

    @staticmethod
    def _card_merchant(purpose: str) -> str:
        """Return the merchant between `` в `` and `` дата ``."""
        after_card = purpose.split(" по карте ", 1)[1]
        after_in = after_card.split(" в ", 1)[1]
        return after_in.split(" дата ", 1)[0].strip()


class OzonPdfAdapter(BankAdapter):
    """Bank adapter for the Ozon PDF statement.

    Detection is filename-first (90), then the first-page body signature
    ``ООО «ОЗОН Банк`` / ``Справка о движении средств`` (85), then the generic
    ``Назначение платежа`` purpose heading (80).
    """

    name = "ozon"
    aliases = ("ozon", "озон", "ozon-bank")
    formats = frozenset({InputFormat.PDF})
    statement_currency = STATEMENT_CURRENCY
    required_headers = ()

    FILENAME_TOKENS: ClassVar[frozenset[str]] = frozenset(
        {"ozon", "озон", "ozonbank", "озонбанк"}
    )
    BODY_SIGNATURES: ClassVar[tuple[str, ...]] = (
        "ООО «ОЗОН Банк",
        "Справка о движении средств",
    )
    PURPOSE_SIGNATURE: ClassVar[str] = "Назначение платежа"
    FILENAME_CONFIDENCE: ClassVar[int] = 90
    BODY_CONFIDENCE: ClassVar[int] = 85
    PURPOSE_CONFIDENCE: ClassVar[int] = 80

    @classmethod
    def probe(cls, ctx: DetectionContext) -> Detection | None:
        """Return a confidence-scored Ozon detection for *ctx*.

        Args:
            ctx: Cached detection context with lazy filename/text signals.

        Returns:
            The detection, or ``None`` when no Ozon signal matches.
        """
        matched_tokens = sorted(cls.FILENAME_TOKENS & ctx.filename_tokens)
        if matched_tokens:
            return Detection(
                cls.name,
                cls.FILENAME_CONFIDENCE,
                f"filename contains {matched_tokens[0]!r}",
            )

        first_page = ctx.pdf_first_page_text()
        if first_page:
            if any(
                marker in first_page for marker in cls.BODY_SIGNATURES
            ):
                return Detection(
                    cls.name,
                    cls.BODY_CONFIDENCE,
                    "first page contains the Ozon statement body signature",
                )
            if cls.PURPOSE_SIGNATURE in first_page:
                return Detection(
                    cls.name,
                    cls.PURPOSE_CONFIDENCE,
                    "first page contains the Ozon purpose heading",
                )
        return None

    def create_extractor(self) -> PdfExtractor:
        """Return the pdfplumber table extractor for this statement."""
        # Imported lazily: the adapters module owns the pdfplumber boundary and
        # must not be loaded from the package import path.
        from ..adapters.pdf_extractors import PdfPlumberTableExtractor

        return PdfPlumberTableExtractor()

    def create_normalizer(self) -> InputNormalizer:
        """Return a table normaliser that keeps only operation rows."""
        from ..adapters.normalizers import TableNormalizer

        return TableNormalizer(
            required_headers=self.required_headers,
            record_predicate=is_record_row,
        )

    def create_mapper(self) -> RowMapper:
        """Return an Ozon mapper wired with the injected parsers."""
        return OzonPdfMapper(
            self._deps.date_parser,
            self._deps.amount_parser,
            currency=self.statement_currency,
        )
