"""Small inline-data builders shared by the pytest suite."""

from __future__ import annotations

from pathlib import Path

from bank_parser.domain.models import InputFormat, SourceLocation
from bank_parser.domain.raw import (
    ColumnLayout,
    NormalizedTable,
    RawLine,
    RawRecord,
    RawRow,
    RawTable,
    RawText,
)


def make_raw_table(
    rows: list[list[str]], path: Path = Path("inline.csv")
) -> RawTable:
    """Build a RawTable from plain cell rows (header included)."""
    raw_rows = tuple(
        RawRow(cells=tuple(row), physical_row=index)
        for index, row in enumerate(rows, start=1)
    )
    return RawTable(
        rows=raw_rows,
        source=SourceLocation(path=path, format=InputFormat.CSV),
    )


def make_raw_text(
    lines: list[tuple[int, str]], path: Path = Path("inline.pdf")
) -> RawText:
    """Build a RawText from (page, text) pairs with 1-based line numbers."""
    return RawText(
        lines=tuple(
            RawLine(text=text, page=page, line=index)
            for index, (page, text) in enumerate(lines, start=1)
        ),
        source=SourceLocation(path=path, format=InputFormat.PDF),
    )


def make_normalized_table(
    rows: list[list[str]],
    header: tuple[str, ...],
    *,
    page: int = 1,
    path: Path = Path("inline.pdf"),
) -> NormalizedTable:
    """Build a NormalizedTable with a fixed header and located records."""
    layout = ColumnLayout.from_header(header)
    records = tuple(
        RawRecord(
            cells=tuple(row),
            layout=layout,
            location=SourceLocation(
                path=path,
                format=InputFormat.PDF,
                page=page,
                data_row=index,
                physical_row=index,
            ),
        )
        for index, row in enumerate(rows, start=1)
    )
    return NormalizedTable(layout=layout, records=records)
