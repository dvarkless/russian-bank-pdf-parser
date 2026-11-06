"""PDF table and text extraction strategies (pdfplumber, pypdf fallback).

pdfplumber and pypdf are imported lazily inside :meth:`extract` so importing
:mod:`bank_parser` or running ``--help`` never loads either library.  The text
extractors return a :class:`~bank_parser.domain.raw.RawText` of
:class:`~bank_parser.domain.raw.RawLine` objects with 1-based page and line
numbers; the table extractor returns a
:class:`~bank_parser.domain.raw.RawTable`.  Every extractor raises
:class:`~bank_parser.errors.NoExtractableContentError` instead of returning an
empty document.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import ClassVar

from ..domain.raw import PdfDocument, RawLine, RawRow, RawTable, RawText
from ..errors import (
    ExtractionError,
    NoExtractableContentError,
    PdfEncryptedError,
    PdfOpenError,
)
from ..ports.extraction import PdfExtractor

__all__ = [
    "FallbackExtractor",
    "PdfPlumberTableExtractor",
    "PdfPlumberTextExtractor",
    "PypdfTextExtractor",
]

logger = logging.getLogger(__name__)


def _page_lines(
    text: str, *, page: int
) -> tuple[RawLine, ...]:
    """Split *text* into located raw lines, preserving blank lines."""
    return tuple(
        RawLine(text=line, page=page, line=line_number)
        for line_number, line in enumerate(text.splitlines(), start=1)
    )


class PdfPlumberTableExtractor:
    """Extract table rows with pdfplumber, one page at a time.

    Every table returned for a page is flattened in extraction order.  Rows
    keep their 1-based page and their 1-based position within that page's
    flattened table rows; ``None`` cells become empty strings.  A document
    without any table rows raises
    :class:`~bank_parser.errors.NoExtractableContentError`.
    """

    name: ClassVar[str] = "pdfplumber-table"

    def extract(self, document: PdfDocument) -> RawTable:
        """Extract table rows from *document*.

        Args:
            document: Acquired PDF document; its path is opened here.

        Returns:
            Raw table rows with 1-based page and physical-row numbers.

        Raises:
            OSError: If the PDF file cannot be opened or read.
            PdfEncryptedError: If the PDF is encrypted.
            PdfOpenError: If pdfplumber cannot parse the PDF structure.
            ExtractionError: If a page's table extraction fails.
            NoExtractableContentError: If no table rows are found.
        """
        source = Path(document.path)

        import pdfplumber
        from pdfminer.pdfdocument import (
            PDFEncryptionError,
            PDFPasswordIncorrect,
        )
        from pdfplumber.utils.exceptions import (
            MalformedPDFException,
            PdfminerException,
        )

        rows: list[RawRow] = []
        page_count = 0
        try:
            with pdfplumber.open(str(source)) as pdf:
                page_count = len(pdf.pages)
                for page_number, page in enumerate(pdf.pages, start=1):
                    try:
                        tables = page.extract_tables() or []
                    except OSError:
                        raise
                    except (PdfminerException, MalformedPDFException) as exc:
                        raise ExtractionError(
                            f"{source} page {page_number}: {self.name} "
                            f"table extraction failed: {exc}"
                        ) from exc
                    physical_row = 0
                    for table in tables:
                        for raw_row in table or ():
                            if raw_row is None:
                                continue
                            physical_row += 1
                            rows.append(
                                RawRow(
                                    cells=tuple(
                                        "" if cell is None else str(cell)
                                        for cell in raw_row
                                    ),
                                    page=page_number,
                                    physical_row=physical_row,
                                )
                            )
        except OSError:
            raise
        except PdfminerException as exc:
            original = exc.args[0] if exc.args else exc
            if isinstance(
                original, (PDFEncryptionError, PDFPasswordIncorrect)
            ):
                raise PdfEncryptedError(
                    f"{source}: PDF is encrypted ({self.name})"
                ) from exc
            raise PdfOpenError(
                f"{source}: cannot open PDF with {self.name}: {original}"
            ) from exc
        except MalformedPDFException as exc:
            raise PdfOpenError(
                f"{source}: cannot open PDF with {self.name}: {exc}"
            ) from exc

        if not rows:
            raise NoExtractableContentError(
                f"{source}: no extractable tables in {page_count} page(s) "
                f"with {self.name}"
            )
        return RawTable(rows=tuple(rows), source=document.source)


class PdfPlumberTextExtractor:
    """Extract page text with pdfplumber, one page at a time.

    The extractor preserves page order and each page's physical line order.
    Blank pages contribute no lines; a document without any non-empty text
    raises :class:`~bank_parser.errors.NoExtractableContentError`.
    """

    name: ClassVar[str] = "pdfplumber-text"

    def extract(self, document: PdfDocument) -> RawText:
        """Extract text lines from *document*.

        Args:
            document: Acquired PDF document; its path is opened here.

        Returns:
            Raw text lines with 1-based page and line numbers.

        Raises:
            OSError: If the PDF file cannot be opened or read.
            PdfEncryptedError: If the PDF is encrypted.
            PdfOpenError: If pdfplumber cannot parse the PDF structure.
            ExtractionError: If a page's text extraction fails.
            NoExtractableContentError: If the document yields no non-empty text.
        """
        source = Path(document.path)

        import pdfplumber
        from pdfminer.pdfdocument import (
            PDFEncryptionError,
            PDFPasswordIncorrect,
        )
        from pdfplumber.utils.exceptions import (
            MalformedPDFException,
            PdfminerException,
        )

        lines: list[RawLine] = []
        page_count = 0
        try:
            with pdfplumber.open(str(source)) as pdf:
                page_count = len(pdf.pages)
                for page_number, page in enumerate(pdf.pages, start=1):
                    try:
                        text = page.extract_text() or ""
                    except OSError:
                        raise
                    except (PdfminerException, MalformedPDFException) as exc:
                        raise ExtractionError(
                            f"{source} page {page_number}: {self.name} "
                            f"text extraction failed: {exc}"
                        ) from exc
                    lines.extend(_page_lines(text, page=page_number))
        except OSError:
            raise
        except PdfminerException as exc:
            original = exc.args[0] if exc.args else exc
            if isinstance(
                original, (PDFEncryptionError, PDFPasswordIncorrect)
            ):
                raise PdfEncryptedError(
                    f"{source}: PDF is encrypted ({self.name})"
                ) from exc
            raise PdfOpenError(
                f"{source}: cannot open PDF with {self.name}: {original}"
            ) from exc
        except MalformedPDFException as exc:
            raise PdfOpenError(
                f"{source}: cannot open PDF with {self.name}: {exc}"
            ) from exc

        if not any(line.text.strip() for line in lines):
            raise NoExtractableContentError(
                f"{source}: no extractable text in {page_count} page(s) "
                f"with {self.name}"
            )
        return RawText(lines=tuple(lines), source=document.source)


class PypdfTextExtractor:
    """Extract page text with pypdf as a best-effort fallback.

    pypdf's line order/spacing differs from pdfplumber on the supported
    statements, so this extractor is only a fallback.  It still refuses to
    return an empty document.
    """

    name: ClassVar[str] = "pypdf-text"

    def extract(self, document: PdfDocument) -> RawText:
        """Extract text lines from *document* using pypdf.

        Args:
            document: Acquired PDF document; its path is opened here.

        Returns:
            Raw text lines with 1-based page and line numbers.

        Raises:
            OSError: If the PDF file cannot be opened or read.
            PdfEncryptedError: If the PDF is encrypted.
            PdfOpenError: If pypdf cannot parse the PDF structure.
            ExtractionError: If a page's text extraction fails.
            NoExtractableContentError: If the document yields no non-empty text.
        """
        source = Path(document.path)

        from pypdf import PdfReader
        from pypdf.errors import (
            FileNotDecryptedError,
            PyPdfError,
            WrongPasswordError,
        )

        try:
            reader = PdfReader(str(source))
        except OSError:
            raise
        except (FileNotDecryptedError, WrongPasswordError) as exc:
            raise PdfEncryptedError(
                f"{source}: PDF is encrypted ({self.name})"
            ) from exc
        except (PyPdfError, ValueError, TypeError) as exc:
            raise PdfOpenError(
                f"{source}: cannot open PDF with {self.name}: {exc}"
            ) from exc

        if getattr(reader, "is_encrypted", False):
            raise PdfEncryptedError(
                f"{source}: PDF is encrypted ({self.name})"
            )

        lines: list[RawLine] = []
        page_count = 0
        try:
            page_count = len(reader.pages)
        except OSError:
            raise
        except (FileNotDecryptedError, WrongPasswordError) as exc:
            raise PdfEncryptedError(
                f"{source}: PDF is encrypted ({self.name})"
            ) from exc
        except (PyPdfError, ValueError, TypeError) as exc:
            raise PdfOpenError(
                f"{source}: cannot open PDF with {self.name}: {exc}"
            ) from exc

        for page_number, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except OSError:
                raise
            except (FileNotDecryptedError, WrongPasswordError) as exc:
                raise PdfEncryptedError(
                    f"{source}: PDF is encrypted ({self.name})"
                ) from exc
            except (PyPdfError, ValueError, TypeError) as exc:
                raise ExtractionError(
                    f"{source} page {page_number}: {self.name} "
                    f"text extraction failed: {exc}"
                ) from exc
            lines.extend(_page_lines(text, page=page_number))

        if not any(line.text.strip() for line in lines):
            raise NoExtractableContentError(
                f"{source}: no extractable text in {page_count} page(s) "
                f"with {self.name}"
            )
        return RawText(lines=tuple(lines), source=document.source)


class FallbackExtractor:
    """Try a primary text extractor and fall back to a secondary one.

    Args:
        primary: Extractor tried first (normally pdfplumber).
        fallback: Extractor tried only when the primary raises
            :class:`~bank_parser.errors.ExtractionError` or returns no text.

    The combined name is ``"<primary>|<fallback>"``.  The class performs no
    record-count validation; that belongs to the bank adapter/mapper.
    """

    def __init__(
        self, primary: PdfExtractor, fallback: PdfExtractor
    ) -> None:
        self._primary = primary
        self._fallback = fallback

    @property
    def name(self) -> str:
        """Return the combined extractor name."""
        return f"{self._primary.name}|{self._fallback.name}"

    def extract(self, document: PdfDocument) -> RawText:
        """Extract with the primary extractor, falling back on failure.

        Args:
            document: Acquired PDF document.

        Returns:
            Non-empty raw text from the first successful extractor.

        Raises:
            OSError: If the input cannot be read (never retried).
            ExtractionError: If both extractors fail or return no text; the
                message names both extractors and their causes.
        """
        source = Path(document.path)
        failures: list[tuple[str, BaseException]] = []
        for extractor in (self._primary, self._fallback):
            try:
                result = extractor.extract(document)
            except ExtractionError as exc:
                logger.debug(
                    "%s could not extract %s: %s",
                    extractor.name,
                    source,
                    exc,
                )
                failures.append((extractor.name, exc))
                continue
            if not result.is_empty():
                return result
            empty = NoExtractableContentError(
                f"{source}: {extractor.name} returned no non-empty text"
            )
            logger.debug("%s returned no text for %s", extractor.name, source)
            failures.append((extractor.name, empty))

        details = "; ".join(
            f"{name}: {failure}" for name, failure in failures
        )
        raise ExtractionError(
            f"{source}: no extractable text; tried {details}"
        ) from (failures[0][1] if failures else None)
