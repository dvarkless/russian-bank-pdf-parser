"""CSV sources: encoding/delimiter detection and raw table readers.

This module is the only place allowed to import :mod:`pandas` (and only lazily,
inside :meth:`PandasTableReader.read`).  It converts the frame to domain
:class:`~bank_parser.domain.raw.RawTable` objects immediately; no DataFrame or
pandas scalar leaks past this module.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from pathlib import Path

from ..domain.models import InputFormat, SourceLocation
from ..domain.raw import RawRow, RawTable
from ..errors import EncodingError, InputError
from ..ports.source import TableReader

__all__ = [
    "CsvDialectDetector",
    "CsvStatementSource",
    "DELIMITERS",
    "ENCODINGS",
    "PandasTableReader",
    "StdlibCsvReader",
]


class CsvDialectDetector:
    """Detect the encoding and delimiter of a CSV export.

    The behaviour matches the v1 reader: encodings are tried in order
    ``utf-8-sig``, ``utf-8``, ``cp1251``; delimiters are counted outside quoted
    sections on the first non-empty line, with a :class:`csv.Sniffer` fallback.
    """

    ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1251")
    DELIMITERS: tuple[str, ...] = (";", ",", "\t")
    DEFAULT_DELIMITER: str = ";"

    @classmethod
    def decode(cls, data: bytes, path: Path) -> str:
        """Decode *data* using the supported encodings in order.

        Args:
            data: Raw file bytes.
            path: Source path, used in the error message.

        Returns:
            The decoded file text.

        Raises:
            EncodingError: When no supported encoding can decode the file.
        """
        for encoding in cls.ENCODINGS:
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise EncodingError(path, cls.ENCODINGS)

    @classmethod
    def count_outside_quotes(cls, line: str, delimiter: str) -> int:
        """Count *delimiter* occurrences outside double quotes."""
        count = 0
        in_quotes = False
        for character in line:
            if character == '"':
                in_quotes = not in_quotes
            elif character == delimiter and not in_quotes:
                count += 1
        return count

    @classmethod
    def detect_delimiter(cls, text: str) -> str:
        """Return the delimiter used by the first non-empty line of *text*."""
        first_line = ""
        for line in text.splitlines():
            if line.strip():
                first_line = line
                break

        if first_line:
            counts = {
                delimiter: cls.count_outside_quotes(first_line, delimiter)
                for delimiter in cls.DELIMITERS
            }
            best = max(counts, key=counts.__getitem__)
            if counts[best] > 0:
                return best

        sample = "\n".join(text.splitlines()[:20])
        try:
            return csv.Sniffer().sniff(
                sample, delimiters=";,\t"
            ).delimiter
        except csv.Error:
            return cls.DEFAULT_DELIMITER


#: Encodings tried, in order, by :class:`CsvDialectDetector`.
ENCODINGS: tuple[str, ...] = CsvDialectDetector.ENCODINGS
#: Delimiters supported by :class:`CsvDialectDetector`.
DELIMITERS: tuple[str, ...] = CsvDialectDetector.DELIMITERS


def _is_blank(cells: tuple[str, ...]) -> bool:
    """Return True when every cell is empty or whitespace."""
    return not any(cell.strip() for cell in cells)


def _read_header_from_text(text: str) -> tuple[str, ...] | None:
    """Return the first non-empty CSV row with header cells cleaned."""
    delimiter = CsvDialectDetector.detect_delimiter(text)
    reader = csv.reader(
        io.StringIO(text, newline=""), delimiter=delimiter
    )
    for row in reader:
        if any(cell.strip() for cell in row):
            return tuple(
                cell.lstrip("\ufeff").strip() for cell in row
            )
    return None


def _build_table(
    rows: Iterable[tuple[str, ...]], path: Path
) -> RawTable:
    """Convert parsed cells into a :class:`RawTable`, skipping blank rows.

    Args:
        rows: Parsed rows in file order (header included).
        path: Source path for the location object.

    Returns:
        A raw table with 1-based physical row numbers for retained rows.
    """
    raw_rows: list[RawRow] = []
    for physical_row, cells in enumerate(rows, start=1):
        if _is_blank(cells):
            continue
        raw_rows.append(
            RawRow(cells=cells, physical_row=physical_row)
        )
    return RawTable(
        rows=tuple(raw_rows),
        source=SourceLocation(Path(path), InputFormat.CSV),
    )


class PandasTableReader:
    """Read a CSV export via pandas and convert it to a :class:`RawTable`.

    pandas is imported lazily and is used only as a string transport
    (``dtype=str``, no inference, no ``NaN``); see ``docs/code_style.md`` §8.
    """

    def read_header(self, path: Path) -> tuple[str, ...] | None:
        """Return the cleaned header row without parsing the whole table.

        Args:
            path: CSV file path.

        Returns:
            Cleaned header cells, or ``None`` when the file has no rows.

        Raises:
            OSError: If the file cannot be read.
            EncodingError: If no supported encoding can decode the file.
        """
        source = Path(path)
        text = CsvDialectDetector.decode(source.read_bytes(), source)
        return _read_header_from_text(text)

    def read(self, path: Path) -> RawTable:
        """Read *path* into a raw table.

        Args:
            path: CSV file path.

        Returns:
            Extracted rows with the header row included when present.

        Raises:
            OSError: If the file cannot be read.
            EncodingError: If no supported encoding can decode the file.
            InputError: If pandas cannot parse the CSV structure.
        """
        source = Path(path)
        text = CsvDialectDetector.decode(source.read_bytes(), source)
        delimiter = CsvDialectDetector.detect_delimiter(text)

        import pandas as pd
        from pandas.errors import EmptyDataError, ParserError

        try:
            frame = pd.read_csv(
                io.StringIO(text),
                sep=delimiter,
                header=None,
                dtype=str,
                keep_default_na=False,
                na_filter=False,
                engine="python",
                on_bad_lines="error",
            )
        except EmptyDataError:
            return _build_table((), source)
        except ParserError as exc:
            raise InputError(
                f"{source}: cannot parse CSV with delimiter "
                f"{delimiter!r}: {exc}"
            ) from exc
        except (ValueError, TypeError) as exc:
            raise InputError(
                f"{source}: cannot parse CSV with delimiter "
                f"{delimiter!r}: {exc}"
            ) from exc

        rows = (
            tuple(str(cell) for cell in row)
            for row in frame.itertuples(index=False, name=None)
        )
        return _build_table(rows, source)


class StdlibCsvReader:
    """Standard-library CSV reader used as an environment fallback.

    It returns the same rows as :class:`PandasTableReader` for the supported
    fixtures and keeps the v1 reader behaviour for legacy callers.
    """

    def read_header(self, path: Path) -> tuple[str, ...] | None:
        """Return the cleaned header row without parsing the whole table.

        Args:
            path: CSV file path.

        Returns:
            Cleaned header cells, or ``None`` when the file has no rows.

        Raises:
            OSError: If the file cannot be read.
            EncodingError: If no supported encoding can decode the file.
        """
        source = Path(path)
        text = CsvDialectDetector.decode(source.read_bytes(), source)
        return _read_header_from_text(text)

    def read(self, path: Path) -> RawTable:
        """Read *path* into a raw table using :mod:`csv`.

        Args:
            path: CSV file path.

        Returns:
            Extracted rows with the header row included when present.

        Raises:
            OSError: If the file cannot be read.
            EncodingError: If no supported encoding can decode the file.
            InputError: If the CSV parser rejects the file.
        """
        source = Path(path)
        text = CsvDialectDetector.decode(source.read_bytes(), source)
        delimiter = CsvDialectDetector.detect_delimiter(text)

        reader = csv.reader(
            io.StringIO(text, newline=""), delimiter=delimiter
        )
        try:
            rows = tuple(tuple(row) for row in reader)
        except csv.Error as exc:
            raise InputError(
                f"{source}: cannot parse CSV with delimiter "
                f"{delimiter!r}: {exc}"
            ) from exc
        return _build_table(rows, source)


class CsvStatementSource:
    """Acquire a CSV statement by delegating to a :class:`TableReader`."""

    format: InputFormat = InputFormat.CSV

    def __init__(self, reader: TableReader) -> None:
        self._reader = reader

    def acquire(self, path: Path) -> RawTable:
        """Read *path* and return its raw table.

        Args:
            path: CSV file path.

        Returns:
            The raw table produced by the injected reader.

        Raises:
            OSError: If the file cannot be read.
            EncodingError: If no supported encoding can decode the file.
            InputError: If the CSV structure cannot be parsed.
        """
        return self._reader.read(Path(path))
