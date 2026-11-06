"""T-Bank CSV parser — v1 compatibility facade over the class-based adapter.

The functional :func:`parse` and :func:`parse_rows` API is kept for callers
that still import ``bank_parser.banks.tbank``.  New code should use
:class:`~bank_parser.banks.tbank_csv.TbankCsvAdapter` through the registry.
Both facades share the same :class:`~bank_parser.banks.tbank_csv.TbankCsvMapper`
as the adapter, so they cannot drift from the class-based pipeline.
"""

from __future__ import annotations

from pathlib import Path

from ..domain.models import InputFormat, SourceLocation, Transaction
from ..domain.parsing import RussianAmountParser, RussianDateParser
from ..domain.raw import NormalizedTable, RawRow, RawTable
from .tbank_csv import TbankCsvAdapter, TbankCsvMapper

__all__ = [
    "ALIASES",
    "BANK_NAME",
    "OPTIONAL_HEADERS",
    "REQUIRED_HEADERS",
    "parse",
    "parse_rows",
]

BANK_NAME = "tbank"
ALIASES = ("tbank", "t-bank", "т-банк", "т банк")

#: Headers without which a T-Bank export cannot be interpreted.
REQUIRED_HEADERS: tuple[str, ...] = TbankCsvMapper.REQUIRED_HEADERS

#: Headers read when present but not required (kept from the v1 surface).
OPTIONAL_HEADERS: tuple[str, ...] = (
    "Валюта операции",
    "Валюта счёта",
    "Категория по-умолчанию",
    "Ваша категория",
    "Сообщение",
    "Статус",
    "Учёт в аналитике",
)

_DATE_PARSER = RussianDateParser()
_AMOUNT_PARSER = RussianAmountParser()
_MAPPER = TbankCsvMapper(_DATE_PARSER, _AMOUNT_PARSER)


def _normalize_rows(rows: list[list[str]], path: Path) -> NormalizedTable:
    """Wrap legacy table rows and normalise them with ``TableNormalizer``.

    Args:
        rows: Table rows including the header row, as returned by
            :func:`bank_parser.readers.read_table`.
        path: Source path used in diagnostics.

    Returns:
        The normalised table expected by :class:`TbankCsvMapper`.

    Raises:
        MissingHeaderError: If a required T-Bank header is absent.
    """
    # Imported lazily: the adapters layer may import the banks package during
    # its own wiring, and the facade must not create an import cycle.
    from ..adapters.normalizers import TableNormalizer

    raw_rows = tuple(
        RawRow(cells=tuple(row), physical_row=index)
        for index, row in enumerate(rows, start=1)
    )
    raw_table = RawTable(
        rows=raw_rows,
        source=SourceLocation(path=path, format=InputFormat.CSV),
    )
    normalizer = TableNormalizer(
        required_headers=TbankCsvAdapter.required_headers
    )
    return normalizer.normalize(raw_table)


def parse_rows(
    rows: list[list[str]], *, source: str = ""
) -> list[Transaction]:
    """Convert T-Bank table rows into transactions (v1-compatible API).

    The first row is the header row.  Columns are resolved by header name,
    completely empty rows are skipped, every other row yields exactly one
    transaction, and input order is preserved.  Rows are never filtered on
    ``Статус`` or ``Учёт в аналитике``.

    Args:
        rows: Table rows as returned by
            :func:`bank_parser.readers.read_table`; the first row is the header.
        source: Optional source name (usually a path) used in error messages.

    Returns:
        Transactions in input order.

    Raises:
        MissingHeaderError: If a required header is absent.
        DateParseError: If a data row's operation date cannot be parsed.
        AmountParseError: If a data row's amount cannot be parsed.
    """
    path = Path(source) if source else Path("<memory>")
    return _MAPPER.map(_normalize_rows(rows, path))


def parse(path: str | Path) -> list[Transaction]:
    """Read a T-Bank CSV export and return its transactions.

    Args:
        path: Path to the T-Bank CSV export.

    Returns:
        Transactions in input order.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: For unreadable, undecodable or malformed input, including
            a missing required header and unparsable dates or amounts.
    """
    # Imported lazily so importing this facade never pulls in the table-reading
    # adapters (and their optional heavy dependencies).
    from ..readers import read_table

    return parse_rows(read_table(path), source=str(path))
