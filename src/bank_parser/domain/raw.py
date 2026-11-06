"""Raw and normalised document containers shared across the parser layers.

The containers here are deliberately dumb: they carry extracted text, row and
page numbers, and a :class:`~bank_parser.domain.models.SourceLocation` for
diagnostics.  They never strip data cells and never parse bank-specific values;
that belongs to normalisers, mappers and the pure parsers.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import TypeAlias, TypeVar

from ..errors import MissingHeaderError
from .models import InputFormat, SourceLocation

__all__ = [
    "ColumnLayout",
    "ExtractedDocument",
    "InputFormat",
    "NormalizedDocument",
    "NormalizedTable",
    "NormalizedText",
    "PdfDocument",
    "RawDocument",
    "RawLine",
    "RawRecord",
    "RawRow",
    "RawTable",
    "RawText",
    "SourceLocation",
]

_T = TypeVar("_T")


def _as_tuple(values: Iterable[_T]) -> tuple[_T, ...]:
    """Return *values* as a tuple, rejecting a bare string."""
    if isinstance(values, str):
        raise ValueError("expected a sequence, not a single string")
    if isinstance(values, tuple):
        return values
    return tuple(values)


def _clean_header(cell: str) -> str:
    """Strip a leading BOM and outer spaces from a header cell only."""
    return cell.lstrip("\ufeff").strip()


@dataclass(frozen=True, slots=True)
class RawRow:
    """One extracted table row.

    Attributes:
        cells: Cell text; ``None`` from a PDF extractor is already ``""``.
        page: 1-based PDF page, when the row came from a PDF.
        physical_row: 1-based row/line in the extracted document.
    """

    cells: tuple[str, ...]
    page: int | None = None
    physical_row: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", _as_tuple(self.cells))


@dataclass(frozen=True, slots=True)
class RawTable:
    """A raw table (CSV or extracted PDF tables) plus its origin.

    Attributes:
        rows: Raw rows in extraction order, header row included when present.
        source: Location of the whole document.
    """

    rows: tuple[RawRow, ...]
    source: SourceLocation

    def __post_init__(self) -> None:
        object.__setattr__(self, "rows", _as_tuple(self.rows))

    def is_empty(self) -> bool:
        """Return True when no row carries any non-whitespace text."""
        return not self.non_empty_rows()

    def non_empty_rows(self) -> tuple[RawRow, ...]:
        """Return the rows that have at least one non-whitespace cell."""
        return tuple(
            row
            for row in self.rows
            if any(cell.strip() for cell in row.cells)
        )


@dataclass(frozen=True, slots=True)
class RawLine:
    """One extracted text line.

    Attributes:
        text: Line text exactly as extracted.
        page: 1-based PDF page.
        line: 1-based physical line on the page.
    """

    text: str
    page: int
    line: int

    def __post_init__(self) -> None:
        if self.page < 1:
            raise ValueError(f"RawLine.page must be >= 1, got {self.page}")
        if self.line < 1:
            raise ValueError(f"RawLine.line must be >= 1, got {self.line}")


@dataclass(frozen=True, slots=True)
class RawText:
    """Extracted text lines plus the document origin.

    Attributes:
        lines: Lines in extraction order.
        source: Location of the whole document.
    """

    lines: tuple[RawLine, ...]
    source: SourceLocation

    def __post_init__(self) -> None:
        object.__setattr__(self, "lines", _as_tuple(self.lines))

    def is_empty(self) -> bool:
        """Return True when every line is blank."""
        return not any(line.text.strip() for line in self.lines)


@dataclass(frozen=True, slots=True)
class PdfDocument:
    """A PDF file acquired by the PDF source but not yet extracted.

    Attributes:
        path: PDF file path.
        page_count: Number of pages, or ``0`` when the count is unknown.
        metadata: Best-effort document metadata (pypdf).
        source: Location of the whole document.
    """

    path: Path
    page_count: int
    metadata: Mapping[str, str]
    source: SourceLocation

    def __post_init__(self) -> None:
        if self.page_count < 0:
            raise ValueError(
                f"PdfDocument.page_count must be >= 0, got {self.page_count}"
            )
        object.__setattr__(
            self, "metadata", MappingProxyType(dict(self.metadata))
        )


@dataclass(frozen=True, slots=True)
class ColumnLayout:
    """Header names and their first-occurrence column indexes.

    Attributes:
        headers: Cleaned header cells in column order.
        index: Header name to column index; duplicates keep the first.
    """

    headers: tuple[str, ...]
    index: Mapping[str, int]

    def __post_init__(self) -> None:
        object.__setattr__(self, "headers", _as_tuple(self.headers))
        object.__setattr__(self, "index", MappingProxyType(dict(self.index)))

    @classmethod
    def from_header(cls, cells: Sequence[str]) -> ColumnLayout:
        """Build a layout from raw header cells.

        Only header cells are BOM-stripped and outer-space-trimmed; the first
        occurrence of a duplicated header wins.

        Args:
            cells: Header cells exactly as extracted.

        Returns:
            The resolved column layout.
        """
        headers = tuple(_clean_header(cell) for cell in cells)
        index: dict[str, int] = {}
        for position, name in enumerate(headers):
            index.setdefault(name, position)
        return cls(headers=headers, index=index)

    def index_of(self, header: str) -> int | None:
        """Return the column index for *header*, or ``None`` when absent."""
        return self.index.get(header)

    def require(
        self, headers: Sequence[str], *, location: SourceLocation
    ) -> None:
        """Ensure every name in *headers* exists.

        Args:
            headers: Required header names.
            location: Source location used in the error message.

        Raises:
            MissingHeaderError: When at least one required header is absent.
        """
        missing = [name for name in headers if name not in self.index]
        if missing:
            raise MissingHeaderError(
                location=location,
                missing=missing,
                found=self.headers,
            )


@dataclass(frozen=True, slots=True)
class RawRecord:
    """One data row bound to its column layout and source location.

    Attributes:
        cells: Cell text in column order.
        layout: Column layout resolved from the table header.
        location: Source location of this record.
    """

    cells: tuple[str, ...]
    layout: ColumnLayout
    location: SourceLocation

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", _as_tuple(self.cells))

    def get(self, header: str) -> str:
        """Return the cell for *header*, or ``""`` when absent."""
        index = self.layout.index_of(header)
        if index is None:
            return ""
        return self.cell(index)

    def cell(self, index: int) -> str:
        """Return the cell at *index*, or ``""`` when out of range."""
        if 0 <= index < len(self.cells):
            return self.cells[index]
        return ""


@dataclass(frozen=True, slots=True)
class NormalizedTable:
    """A table normalised to a resolved layout and data records.

    Attributes:
        layout: Column layout resolved from the table header.
        records: Data records in input order, header excluded.
    """

    layout: ColumnLayout
    records: tuple[RawRecord, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "records", _as_tuple(self.records))


@dataclass(frozen=True, slots=True)
class NormalizedText:
    """Normalised text lines ready for a line-oriented mapper.

    Attributes:
        lines: Retained lines in page/line order.
        source: Location of the whole document.
    """

    lines: tuple[RawLine, ...]
    source: SourceLocation

    def __post_init__(self) -> None:
        object.__setattr__(self, "lines", _as_tuple(self.lines))


#: Documents a source can acquire: a CSV table or a not-yet-extracted PDF.
RawDocument: TypeAlias = RawTable | PdfDocument
#: Documents an extractor can produce: table cells or text lines.
ExtractedDocument: TypeAlias = RawTable | RawText
#: Documents a normaliser can produce: a normalised table or text.
NormalizedDocument: TypeAlias = NormalizedTable | NormalizedText
