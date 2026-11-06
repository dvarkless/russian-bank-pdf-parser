"""Input normalisers: raw extracted content to normalised statement documents."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from ..domain.models import SourceLocation
from ..domain.raw import (
    ColumnLayout,
    ExtractedDocument,
    NormalizedTable,
    NormalizedText,
    RawRecord,
    RawRow,
    RawTable,
    RawText,
)
from ..errors import MissingHeaderError, NormalizationError

__all__ = ["TableNormalizer", "TextNormalizer"]


def _clean_header(cell: str) -> str:
    """Strip a leading BOM and outer spaces from a header cell only."""
    return cell.lstrip("\ufeff").strip()


class TableNormalizer:
    """Normalise a raw table into a layout plus located data records.

    Args:
        required_headers: Header names that must be present. When empty, the
            first non-empty row is treated as the header.
        record_predicate: Optional content predicate applied to every row after
            the header. Rows that do not match are skipped (used by PDF table
            statements whose repeated header/footer rows must be ignored).
        skip_blank_rows: Skip rows whose cells are all empty or whitespace.

    The normaliser never strips data cells, never reorders records, and numbers
    ``data_row`` from 1 over the records it actually keeps.
    """

    def __init__(
        self,
        *,
        required_headers: Sequence[str] = (),
        record_predicate: Callable[[RawRow], bool] | None = None,
        skip_blank_rows: bool = True,
    ) -> None:
        self._required_headers = tuple(required_headers)
        self._record_predicate = record_predicate
        self._skip_blank_rows = skip_blank_rows

    def normalize(self, document: ExtractedDocument) -> NormalizedTable:
        """Normalise *document* into a :class:`NormalizedTable`.

        Args:
            document: Raw table extracted from a CSV file or a PDF table.

        Returns:
            The resolved layout and located data records.

        Raises:
            NormalizationError: When *document* is not a raw table or is empty.
            MissingHeaderError: When a required header is absent.
        """
        if not isinstance(document, RawTable):
            raise NormalizationError(
                f"{self._describe_source(document)}: expected a raw table, "
                f"got {type(document).__name__}"
            )

        header_index = self._find_header_index(document)
        header_row = document.rows[header_index]
        layout = ColumnLayout.from_header(header_row.cells)
        if self._required_headers:
            layout.require(
                self._required_headers, location=document.source
            )

        records: list[RawRecord] = []
        data_row = 0
        for row in document.rows[header_index + 1 :]:
            if self._skip_blank_rows and not any(
                cell.strip() for cell in row.cells
            ):
                continue
            if (
                self._record_predicate is not None
                and not self._record_predicate(row)
            ):
                continue
            data_row += 1
            location = SourceLocation(
                path=document.source.path,
                format=document.source.format,
                page=row.page,
                data_row=data_row,
                physical_row=row.physical_row,
            )
            records.append(
                RawRecord(
                    cells=row.cells,
                    layout=layout,
                    location=location,
                )
            )

        return NormalizedTable(
            layout=layout,
            records=tuple(records),
        )

    def _find_header_index(self, document: RawTable) -> int:
        """Return the index of the header row, raising a clear error if absent."""
        if not document.rows:
            if self._required_headers:
                raise MissingHeaderError(
                    location=document.source,
                    missing=self._required_headers,
                    found=(),
                )
            raise NormalizationError(
                f"{document.source.describe()}: table is empty"
            )

        if not self._required_headers:
            for index, row in enumerate(document.rows):
                if any(cell.strip() for cell in row.cells):
                    return index
            raise NormalizationError(
                f"{document.source.describe()}: table is empty"
            )

        for index, row in enumerate(document.rows):
            if not any(cell.strip() for cell in row.cells):
                continue
            names = {_clean_header(cell) for cell in row.cells}
            if all(name in names for name in self._required_headers):
                return index

        first_row = next(
            (
                row
                for row in document.rows
                if any(cell.strip() for cell in row.cells)
            ),
            None,
        )
        if first_row is None:
            raise MissingHeaderError(
                location=document.source,
                missing=self._required_headers,
                found=(),
            )
        layout = ColumnLayout.from_header(first_row.cells)
        layout.require(
            self._required_headers, location=document.source
        )
        # ``require`` always raises when a required header is missing.
        raise NormalizationError(
            f"{document.source.describe()}: cannot resolve table header"
        )

    @staticmethod
    def _describe_source(document: ExtractedDocument) -> str:
        """Return a readable source name for a wrong-document error."""
        source = getattr(document, "source", None)
        if isinstance(source, SourceLocation):
            return source.describe()
        path = getattr(document, "path", None)
        return str(path) if path is not None else "input"


class TextNormalizer:
    """Drop configured boilerplate lines from an extracted text document.

    Args:
        skip_patterns: Patterns whose matching lines are page furniture or
            legal boilerplate. The mapper's state machine is still responsible
            for ignoring any non-record line that survives.
    """

    def __init__(
        self, *, skip_patterns: Sequence[re.Pattern[str]] = ()
    ) -> None:
        self._skip_patterns = tuple(skip_patterns)

    def normalize(self, document: ExtractedDocument) -> NormalizedText:
        """Return the retained text lines in original page/line order.

        Args:
            document: Raw text extracted from a PDF.

        Returns:
            The retained lines wrapped in :class:`NormalizedText`.

        Raises:
            NormalizationError: When *document* is not raw text.
        """
        if not isinstance(document, RawText):
            source = getattr(document, "source", None)
            name = (
                source.describe()
                if isinstance(source, SourceLocation)
                else "input"
            )
            raise NormalizationError(
                f"{name}: expected raw text, got "
                f"{type(document).__name__}"
            )

        lines = tuple(
            line
            for line in document.lines
            if not any(
                pattern.search(line.text)
                for pattern in self._skip_patterns
            )
        )
        return NormalizedText(lines=lines, source=document.source)
