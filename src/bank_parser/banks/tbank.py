"""T-Bank (Tinkoff) CSV statement parser.

This module turns a T-Bank export table (already read into rows of text cells by
:func:`bank_parser.readers.read_table`) into canonical
:class:`bank_parser.models.Transaction` objects.

Column resolution is done by header name, never by position, so reordered or
extra columns in the export do not break parsing.  Only the three required
headers (``Дата операции``, ``Сумма операции``, ``Описание``) must be present;
all other T-Bank columns are optional and are read when available.

Money is handled with :class:`decimal.Decimal` only -- never binary floats.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from ..models import Transaction
from ..readers import read_table

__all__ = ["BANK_NAME", "ALIASES", "parse_rows", "parse"]

BANK_NAME = "tbank"
ALIASES = ("tbank", "t-bank", "т-банк", "т банк")

#: Headers without which a T-Bank export cannot be interpreted.
REQUIRED_HEADERS: tuple[str, ...] = (
    "Дата операции",
    "Сумма операции",
    "Описание",
)

#: Headers that are read when present but are not mandatory.
OPTIONAL_HEADERS: tuple[str, ...] = (
    "Валюта операции",
    "Валюта счёта",
    "Категория по-умолчанию",
    "Ваша категория",
    "Сообщение",
    "Статус",
    "Учёт в аналитике",
)

#: Supported date layouts, tried in this order.
DATE_FORMATS: tuple[str, ...] = (
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y",
    "%d/%m/%Y",
)

#: Characters used as a minus sign by various exporters/OS settings.
_MINUS_SIGNS = "\u2212\u2013\u2014\u2012\u2015"

#: Currency symbols/letters that may surround an amount.
_CURRENCY_SYMBOLS = "₽$€£¥₸₴₹₺₼₾¢"


def _clean_header(cell: str) -> str:
    """Return a header cell without a leading BOM and without outer spaces."""
    return cell.lstrip("\ufeff").strip()


def _source_prefix(source: str) -> str:
    """Format the optional source name used at the start of error messages."""
    return f"{source}: " if source else ""


def _row_error(message: str, *, row_number: int, source: str = "") -> ValueError:
    """Build a ``ValueError`` that names the 1-based data row and the source."""
    return ValueError(f"{_source_prefix(source)}data row {row_number}: {message}")


def _resolve_columns(header: list[str], *, source: str = "") -> dict[str, int]:
    """Map every known header name to its column index.

    :param header: the header row as read from the export.
    :param source: optional source name used in error messages.
    :raises ValueError: when one or more required headers are missing.
    """
    columns: dict[str, int] = {}
    for index, cell in enumerate(header):
        name = _clean_header(cell)
        # The first occurrence of a duplicated header wins.
        columns.setdefault(name, index)

    missing = [name for name in REQUIRED_HEADERS if name not in columns]
    if missing:
        quoted = ", ".join(repr(name) for name in missing)
        raise ValueError(
            f"{_source_prefix(source)}T-Bank table is missing required "
            f"header(s): {quoted}"
        )
    return columns


def _cell(row: list[str], column: int | None) -> str:
    """Return the text of ``row`` at ``column``, or ``""`` when absent."""
    if column is None or column >= len(row):
        return ""
    return row[column]


def _parse_date(raw: str, *, row_number: int, source: str = "") -> date:
    """Parse a T-Bank operation date.

    Tries ``%d.%m.%Y %H:%M:%S``, then ``%d.%m.%Y``, then ``%d/%m/%Y``.
    """
    text = raw.strip()
    if text:
        for date_format in DATE_FORMATS:
            try:
                return datetime.strptime(text, date_format).date()
            except ValueError:
                continue
    accepted = ", ".join(DATE_FORMATS)
    raise _row_error(
        f"cannot parse operation date {raw!r} (expected one of: {accepted})",
        row_number=row_number,
        source=source,
    )


def _parse_amount(raw: str, *, row_number: int, source: str = "") -> Decimal:
    """Parse a signed T-Bank operation amount into a :class:`~decimal.Decimal`.

    Accepts comma or dot decimal separators, a Unicode minus sign, NBSP/thin
    spaces and other Unicode whitespace used as thousands separators, and
    optional currency symbols, e.g. ``"-900,00"``, ``"−1 234,56 ₽"``.
    """
    chars: list[str] = []
    for char in raw.strip():
        if char.isspace():
            continue
        if char in _MINUS_SIGNS:
            chars.append("-")
        elif char in _CURRENCY_SYMBOLS:
            continue
        else:
            chars.append(char)
    cleaned = "".join(chars)

    if not cleaned:
        raise _row_error(
            f"cannot parse operation amount {raw!r}: no digits found",
            row_number=row_number,
            source=source,
        )

    if "," in cleaned and "." in cleaned:
        # Both separators present: the right-most one is the decimal separator.
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", ".")

    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise _row_error(
            f"cannot parse operation amount {raw!r}",
            row_number=row_number,
            source=source,
        ) from exc


def parse_rows(rows: list[list[str]], *, source: str = "") -> list[Transaction]:
    """Convert T-Bank table rows into transactions.

    The first row is the header row; columns are resolved by header name.
    Completely empty rows are skipped, every other row produces exactly one
    transaction, and input order is preserved.  Rows are never filtered on
    ``Статус`` or ``Учёт в аналитике``.

    :param rows: table rows as returned by
        :func:`bank_parser.readers.read_table`; the first row is the header.
    :param source: optional source name (usually a path) used in error messages.
    :raises ValueError: on a missing required header, or on a date/amount that
        cannot be parsed; the message names the 1-based data-row number.
    """
    header_index: int | None = None
    for index, row in enumerate(rows):
        if any(cell.strip() for cell in row):
            header_index = index
            break
    if header_index is None:
        raise ValueError(
            f"{_source_prefix(source)}T-Bank table is empty; required "
            f"header(s) not found: "
            f"{', '.join(repr(name) for name in REQUIRED_HEADERS)}"
        )

    columns = _resolve_columns(rows[header_index], source=source)
    index_date = columns["Дата операции"]
    index_amount = columns["Сумма операции"]
    index_description = columns["Описание"]
    index_currency = columns.get("Валюта операции")
    index_account_currency = columns.get("Валюта счёта")
    index_category = columns.get("Категория по-умолчанию")
    index_user_category = columns.get("Ваша категория")
    index_message = columns.get("Сообщение")

    transactions: list[Transaction] = []
    row_number = 0
    for row in rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            continue  # Skip completely empty rows.
        row_number += 1

        signed_amount = _parse_amount(
            _cell(row, index_amount), row_number=row_number, source=source
        )
        if signed_amount < 0:
            operation_type = "Списание"
        elif signed_amount > 0:
            operation_type = "Пополнение"
        else:
            operation_type = "Списание"

        currency = _cell(row, index_currency).strip()
        if not currency:
            currency = _cell(row, index_account_currency).strip()

        category = _cell(row, index_category).strip()
        if not category:
            category = _cell(row, index_user_category).strip()

        transactions.append(
            Transaction(
                date=_parse_date(
                    _cell(row, index_date), row_number=row_number, source=source
                ),
                merchant=_cell(row, index_description).strip(),
                amount=abs(signed_amount),
                currency=currency,
                category=category,
                operation_type=operation_type,
                comment=_cell(row, index_message).strip(),
            )
        )
    return transactions


def parse(path: str | Path) -> list[Transaction]:
    """Read a T-Bank export file and return its transactions.

    :param path: path to the T-Bank CSV export.
    :raises ValueError: when required headers are missing or a data row cannot
        be parsed.
    """
    return parse_rows(read_table(path), source=str(path))
