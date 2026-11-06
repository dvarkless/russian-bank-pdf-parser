"""Legacy compatibility facade for the v1 delimiter/encoding-tolerant reader.

New code should use :class:`bank_parser.adapters.csv_source.CsvStatementSource`
and the pipeline. ``read_table`` keeps the v1 return shape (``list[list[str]]``)
and continues to use the standard-library reader, which is byte-for-byte
compatible with the original implementation.
"""

from __future__ import annotations

from pathlib import Path

from .adapters.csv_source import (
    DELIMITERS,
    ENCODINGS,
    CsvDialectDetector,
    StdlibCsvReader,
)

__all__ = [
    "DELIMITERS",
    "ENCODINGS",
    "read_table",
]

_DEFAULT_DELIMITER = CsvDialectDetector.DEFAULT_DELIMITER
_READER = StdlibCsvReader()


def read_table(path: str | Path) -> list[list[str]]:
    """Read a bank export file into a list of rows (legacy API).

    The encoding is detected by trying ``utf-8-sig``, ``utf-8`` and ``cp1251``
    in order.  The delimiter is detected among ``;``, ``,`` and ``\\t`` from the
    first non-empty line.  Standard CSV double-quote quoting is honoured, so
    quoted cells may contain delimiters or newlines.  Both CRLF and LF line
    endings are accepted.

    Rows whose cells are all empty/whitespace are skipped; cell text is
    otherwise returned unchanged (including internal non-breaking spaces).
    The header row, when present, is included as the first row.

    Args:
        path: Path to the export file.

    Returns:
        Non-empty rows of the table, each a list of string cells.

    Raises:
        FileNotFoundError: If *path* does not exist.
        bank_parser.errors.EncodingError: If the file cannot be decoded with
            the supported encodings (a ``ValueError``).
    """
    table = _READER.read(Path(path))
    return [list(row.cells) for row in table.rows]
