"""Delimiter/encoding tolerant table reader for bank export files."""

from __future__ import annotations

import csv
import io
from pathlib import Path

ENCODINGS: tuple[str, ...] = ("utf-8-sig", "utf-8", "cp1251")
"""Encodings tried, in order, when decoding an export file."""

DELIMITERS: tuple[str, ...] = (";", ",", "\t")
"""Delimiters supported by :func:`read_table`."""

_DEFAULT_DELIMITER = ";"


def _decode(data: bytes, path: Path) -> str:
    """Decode *data* trying the supported encodings in order.

    Args:
        data: Raw file contents.
        path: Source path, used only for error messages.

    Returns:
        The decoded file contents.

    Raises:
        ValueError: If none of :data:`ENCODINGS` can decode the file.
    """
    for encoding in ENCODINGS:
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError(
        f"Could not decode {path}: tried {', '.join(ENCODINGS)} but the file is "
        "not valid in any of them."
    )


def _count_outside_quotes(line: str, delimiter: str) -> int:
    """Count *delimiter* occurrences that are not inside double quotes."""
    count = 0
    in_quotes = False
    for char in line:
        if char == '"':
            in_quotes = not in_quotes
        elif char == delimiter and not in_quotes:
            count += 1
    return count


def _detect_delimiter(text: str) -> str:
    """Return the delimiter used by the first non-empty line of *text*.

    Counting is done outside quoted sections, so a comma decimal separator in a
    quoted or unquoted data cell cannot outvote the real delimiter in the header.
    Falls back to :data:`_DEFAULT_DELIMITER` when no candidate is present.
    """
    first_line = ""
    for line in text.splitlines():
        if line.strip():
            first_line = line
            break

    if first_line:
        counts = {
            delimiter: _count_outside_quotes(first_line, delimiter)
            for delimiter in DELIMITERS
        }
        best = max(counts, key=counts.__getitem__)
        if counts[best] > 0:
            return best

    # No delimiter found in the header: let the standard parser try a sample.
    sample = "\n".join(text.splitlines()[:20])
    try:
        return csv.Sniffer().sniff(sample, delimiters=";,\t").delimiter
    except csv.Error:
        return _DEFAULT_DELIMITER


def read_table(path: str | Path) -> list[list[str]]:
    """Read a bank export file into a list of rows.

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
        ValueError: If the file cannot be decoded with the supported encodings.
    """
    source = Path(path)
    text = _decode(source.read_bytes(), source)
    delimiter = _detect_delimiter(text)

    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter)
    return [row for row in reader if row and any(cell.strip() for cell in row)]
