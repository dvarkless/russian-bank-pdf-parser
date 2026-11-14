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
from collections.abc import Callable
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

from ..domain.models import InputFormat, Money, Transaction
from ..domain.raw import (
    NormalizedDocument,
    NormalizedTable,
    RawRow,
)
from ..errors import (
    AmountParseError,
    DateParseError,
    NormalizationError,
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
_PURPOSE_SENDER = "Отправитель:"
_PURPOSE_OWN_FUNDS = "Перевод собственных средств"
_PURPOSE_OZON_PLATFORM = "Платформе Ozon"
_PURPOSE_GOODS = "Оплата товаров"
_PURPOSE_TIPS = "Чаевые по заказу"
_PURPOSE_CASHBACK = "Выплата кешбека"
_PURPOSE_DEPOSIT_PLACEMENT = "Размещение вклада"
_PURPOSE_DEPOSIT_RETURN = "Возврат вклада"
_PURPOSE_REFUND = "Возврат оплаты"
_PURPOSE_BANK_CLIENT = "Перевод клиенту Банка"
_PURPOSE_BILL_PAYMENT = "Платеж в пользу"
_PURPOSE_CASH_WITHDRAWAL = "Снятие наличных"
_PURPOSE_INCOMING_TRANSFER = "Зачисление по переводу"
_PURPOSE_ERRONEOUS_RETURN = "Возв.ошиб"
_PURPOSE_IP_DEBT = "оплата задолженности по ИП"

_CATEGORY_SBP = "Перевод через СБП"
_CATEGORY_OWN_FUNDS = "Перевод собственных средств"
_CATEGORY_OZON_PLATFORM = "Оплата товаров/услуг на Платформе Ozon"
_CATEGORY_GOODS = "Оплата товаров"
_CATEGORY_TIPS = "Чаевые по заказу"
_CATEGORY_CASHBACK = "Кешбэк"
_CATEGORY_DEPOSIT_PLACEMENT = "Размещение вклада"
_CATEGORY_DEPOSIT_RETURN = "Возврат вклада"
_CATEGORY_CARD_REFUND = "Возврат оплаты товаров"
_CATEGORY_PLATFORM_REFUND = (
    "Возврат оплаты товаров/услуг на Платформе Ozon"
)
_CATEGORY_BANK_CLIENT = "Перевод клиенту Банка"
_CATEGORY_MTS = "Платеж в пользу МТС"
_CATEGORY_TSZH = "Платеж в пользу ТСЖ"
_CATEGORY_BILL_PAYMENT = "Платежи"
_CATEGORY_CASH_WITHDRAWAL = "Снятие наличных"
_CATEGORY_INCOMING_TRANSFER = "Зачисление по переводу"
_CATEGORY_ERRONEOUS_RETURN = "Возврат ошибочного перевода"
_CATEGORY_IP_DEBT = "Оплата задолженности по ИП"
_CATEGORY_OTHER = "Прочие операции"

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
        account_reader: Callable[[Path], str] | None = None,
    ) -> None:
        """Initialise the mapper with injected parsers and the currency code.

        Args:
            date_parser: Context-free parser for operation timestamps.
            amount_parser: Context-free parser for signed amounts.
            currency: Currency code applied to every transaction (``"RUR"``).
            account_reader: Optional reader that returns the Ozon account
                number from the source PDF path; when omitted, the canonical
                bank name is used instead.
        """
        self._date_parser = date_parser
        self._amount_parser = amount_parser
        self._currency = currency
        self._account_reader = account_reader

    def map(self, document: NormalizedDocument) -> list[Transaction]:
        """Map a normalised Ozon table to transactions.

        Every record yields exactly one transaction, in input order.  The
        date is the operation timestamp (time dropped); the amount comes from
        the RUB column (the account-currency column is cross-checked when
        present); the purpose is classified by the ordered rules; a single
        account label, resolved from the statement's first page, is applied
        to every row.

        Args:
            document: Normalised table produced by the Ozon ``TableNormalizer``.

        Returns:
            Transactions in input order.

        Raises:
            NormalizationError: If *document* is not a ``NormalizedTable``.
            DateParseError: If a record's operation timestamp cannot be parsed.
            AmountParseError: If a record's amount cannot be parsed.
            ValidationError: If the two amount columns disagree.
        """
        if not isinstance(document, NormalizedTable):
            raise NormalizationError(
                "OzonPdfMapper expects a NormalizedTable, got "
                f"{type(document).__name__}"
            )

        account = self._resolve_account(document)
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
            category, merchant = self._classify_purpose(purpose)

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
                    account=account,
                )
            )
        return transactions

    def _resolve_account(self, document: NormalizedTable) -> str:
        """Return the Ozon account label applied to every transaction.

        The source path is taken from the first record's location; the
        injected account reader extracts the ``Номер лицевого счёта`` number
        from page 1. An unreadable account falls back to the bank name.

        Args:
            document: Normalised table whose records carry the source path.

        Returns:
            The account number, or ``"ozon"`` when it cannot be read.
        """
        if self._account_reader is None or not document.records:
            return "ozon"
        path = document.records[0].location.path
        account = self._account_reader(path).strip()
        return account or "ozon"

    def _classify_purpose(self, purpose: str) -> tuple[str, str]:
        """Return ``(category, merchant)`` for a normalised purpose.

        The rules are ordered: refunds are recognised before the matching
        payment rules, incoming SBP transfers use ``Отправитель:`` while
        outgoing ones use ``Получатель:``, and the odd 2026 statement purposes
        (cashback, deposits, bill payments, cash withdrawal, Card2Card,
        erroneous/debt transfers) each get a descriptive category.  A purpose
        that still matches nothing falls back to ``Прочие операции`` so that a
        new statement does not block the whole conversion.

        Args:
            purpose: Purpose text with whitespace runs collapsed.

        Returns:
            The category and merchant for the first matching rule.
        """
        if _PURPOSE_SBP in purpose:
            if _PURPOSE_RECIPIENT in purpose:
                return _CATEGORY_SBP, self._sbp_party(
                    purpose, _PURPOSE_RECIPIENT
                )
            if _PURPOSE_SENDER in purpose:
                return _CATEGORY_SBP, self._sbp_party(
                    purpose, _PURPOSE_SENDER
                )

        if _PURPOSE_CASHBACK in purpose:
            return _CATEGORY_CASHBACK, ""

        if _PURPOSE_OWN_FUNDS in purpose:
            return _CATEGORY_OWN_FUNDS, ""

        if _PURPOSE_DEPOSIT_PLACEMENT in purpose:
            return _CATEGORY_DEPOSIT_PLACEMENT, ""

        if _PURPOSE_DEPOSIT_RETURN in purpose:
            return _CATEGORY_DEPOSIT_RETURN, ""

        if _PURPOSE_REFUND in purpose and _PURPOSE_OZON_PLATFORM in purpose:
            return _CATEGORY_PLATFORM_REFUND, ""

        if _PURPOSE_REFUND in purpose and " по карте " in purpose:
            return _CATEGORY_CARD_REFUND, self._card_merchant(purpose)

        if _PURPOSE_BANK_CLIENT in purpose:
            return _CATEGORY_BANK_CLIENT, ""

        if _PURPOSE_BILL_PAYMENT in purpose:
            payee = self._bill_payee(purpose)
            if "МТС" in payee:
                return _CATEGORY_MTS, payee
            if "ТСЖ" in payee:
                return _CATEGORY_TSZH, payee
            return _CATEGORY_BILL_PAYMENT, payee

        if _PURPOSE_CASH_WITHDRAWAL in purpose:
            return _CATEGORY_CASH_WITHDRAWAL, self._cash_withdrawal_merchant(
                purpose
            )

        if _PURPOSE_INCOMING_TRANSFER in purpose:
            return _CATEGORY_INCOMING_TRANSFER, self._incoming_transfer_source(
                purpose
            )

        if _PURPOSE_ERRONEOUS_RETURN in purpose:
            return _CATEGORY_ERRONEOUS_RETURN, ""

        if _PURPOSE_IP_DEBT in purpose:
            return _CATEGORY_IP_DEBT, ""

        if _PURPOSE_OZON_PLATFORM in purpose:
            merchant = (
                _OZON_PREMIUM if _OZON_PREMIUM in purpose else ""
            )
            return _CATEGORY_OZON_PLATFORM, merchant

        if self._is_card_payment(purpose):
            return _CATEGORY_GOODS, self._card_merchant(purpose)

        if _PURPOSE_TIPS in purpose:
            return _CATEGORY_TIPS, ""

        return _CATEGORY_OTHER, ""

    @staticmethod
    def _sbp_party(purpose: str, marker: str) -> str:
        """Return the sender/recipient text after an SBP marker.

        The party ends at ``. Без НДС`` or at the end of the purpose.
        """
        after_marker = purpose.split(marker, 1)[1]
        return after_marker.split(_WITHOUT_VAT_SUFFIX, 1)[0].strip()

    @staticmethod
    def _bill_payee(purpose: str) -> str:
        """Return the payee after ``Платеж в пользу`` up to a comma."""
        after_marker = purpose.split(_PURPOSE_BILL_PAYMENT, 1)[1]
        return after_marker.split(",", 1)[0].strip()

    @staticmethod
    def _cash_withdrawal_merchant(purpose: str) -> str:
        """Return the ATM bank for a cash-withdrawal purpose."""
        if "ОЗОН Банка" in purpose:
            return "ОЗОН Банк"
        return ""

    @staticmethod
    def _incoming_transfer_source(purpose: str) -> str:
        """Return the card-transfer source bank (e.g. ``T-Bank``)."""
        if "T-Bank" in purpose:
            return "T-Bank"
        return ""

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
        """Return an Ozon mapper wired with the injected parsers and reader."""
        # Imported lazily: the adapter owns the pdfplumber peek boundary and
        # must not load it from the package import path.
        from ..adapters.peeks import read_ozon_account

        return OzonPdfMapper(
            self._deps.date_parser,
            self._deps.amount_parser,
            currency=self.statement_currency,
            account_reader=read_ozon_account,
        )
