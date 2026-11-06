"""Cheap detection peeks for CSV headers and PDF first pages."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from pathlib import Path

from ..errors import BankParserError
from ..ports.source import TableReader

__all__ = ["PandasCsvPeek", "PdfPlumberPdfPeek"]

logger = logging.getLogger(__name__)


class PandasCsvPeek:
    """Read a CSV header through the injected table reader.

    The peek never imports pandas itself; it reuses the reader used by the
    source so detection and acquisition see the same dialect.
    """

    def __init__(self, reader: TableReader) -> None:
        self._reader = reader

    def header(self, path: Path) -> tuple[str, ...] | None:
        """Return the first non-empty row's cells, or ``None`` when unavailable.

        Args:
            path: CSV file path.

        Returns:
            Cleaned header cells, or ``None`` when the file has no rows or
            cannot be interpreted as CSV.

        Raises:
            OSError: If the file cannot be read.
        """
        header_reader = getattr(self._reader, "read_header", None)
        try:
            if callable(header_reader):
                return header_reader(Path(path))
            table = self._reader.read(Path(path))
        except BankParserError as exc:
            logger.debug("CSV peek failed for %s: %s", path, exc)
            return None
        rows = table.non_empty_rows()
        if not rows:
            return None
        return tuple(
            cell.lstrip("\ufeff").strip() for cell in rows[0].cells
        )


class PdfPlumberPdfPeek:
    """Best-effort first-page text and metadata for PDF detection.

    pdfplumber and pypdf are imported lazily inside the methods so importing
    the package (or ``--help``) never loads either library.
    """

    def first_page_text(self, path: Path) -> str | None:
        """Return page 1 text, falling back from pdfplumber to pypdf.

        Args:
            path: PDF file path.

        Returns:
            First-page text, or ``None`` when neither library can extract it.

        Raises:
            OSError: If the file cannot be opened.
        """
        text = self._pdfplumber_first_page(path)
        if text and text.strip():
            return text
        return self._pypdf_first_page(path)

    def metadata(self, path: Path) -> Mapping[str, str]:
        """Return best-effort PDF metadata via pypdf.

        Args:
            path: PDF file path.

        Returns:
            Normalised metadata mapping; empty when pypdf cannot read it.

        Raises:
            OSError: If the file cannot be opened.
        """
        try:
            from pypdf import PdfReader
            from pypdf.errors import PyPdfError
        except ImportError:  # pragma: no cover - dependency is declared
            return {}

        try:
            reader = PdfReader(str(path))
        except OSError:
            raise
        except (PyPdfError, ValueError, TypeError) as exc:
            logger.debug("pypdf metadata peek failed for %s: %s", path, exc)
            return {}

        raw_metadata = getattr(reader, "metadata", None)
        if raw_metadata is None:
            return {}
        metadata: dict[str, str] = {}
        try:
            for key, value in dict(raw_metadata).items():
                name = str(key).lstrip("/")
                if name and value is not None:
                    metadata[name] = str(value)
        except (PyPdfError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("pypdf metadata normalisation failed: %s", exc)
            return {}
        return metadata

    def _pdfplumber_first_page(self, path: Path) -> str | None:
        """Extract page 1 with pdfplumber, or return ``None``."""
        try:
            import pdfplumber
            from pdfminer.pdfexceptions import PDFException
            from pdfplumber.utils.exceptions import PdfminerException
        except ImportError:  # pragma: no cover - dependency is declared
            return None

        try:
            with pdfplumber.open(str(path)) as pdf:
                if not pdf.pages:
                    return None
                return pdf.pages[0].extract_text() or ""
        except OSError:
            raise
        except (
            PDFException,
            PdfminerException,
            ValueError,
            TypeError,
            RuntimeError,
        ) as exc:
            # pdfplumber wraps pdfminer failures (corrupt/encrypted PDFs) in
            # PdfminerException, which is not a PDFException subclass.
            logger.debug("pdfplumber text peek failed for %s: %s", path, exc)
            return None

    def _pypdf_first_page(self, path: Path) -> str | None:
        """Extract page 1 with pypdf, or return ``None``."""
        try:
            from pypdf import PdfReader
            from pypdf.errors import PyPdfError
        except ImportError:  # pragma: no cover - dependency is declared
            return None

        try:
            reader = PdfReader(str(path))
            if not reader.pages:
                return None
            return reader.pages[0].extract_text() or ""
        except OSError:
            raise
        except (PyPdfError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("pypdf text peek failed for %s: %s", path, exc)
            return None
