"""PDF source acquisition: page count and metadata, without text extraction."""

from __future__ import annotations

import logging
from pathlib import Path

from ..domain.models import InputFormat, SourceLocation
from ..domain.raw import PdfDocument
from ..errors import PdfEncryptedError
from ..ports.source import PdfMetadata, PdfMetadataReader

__all__ = ["PdfStatementSource", "PypdfMetadataReader"]

logger = logging.getLogger(__name__)


class PypdfMetadataReader:
    """Read a PDF's page count and metadata with pypdf, best effort.

    pypdf is imported lazily; a file that pypdf cannot parse still yields an
    empty :class:`PdfMetadata` so the extraction stage can report the real
    failure. Encrypted files fail immediately.
    """

    def read(self, path: Path) -> PdfMetadata:
        """Return page count and metadata for *path*.

        Args:
            path: PDF file path.

        Returns:
            Page count (``0`` when unknown) and normalised metadata.

        Raises:
            OSError: If the file cannot be read.
            PdfEncryptedError: If the PDF is encrypted.
        """
        try:
            from pypdf import PdfReader
            from pypdf.errors import (
                FileNotDecryptedError,
                PyPdfError,
                WrongPasswordError,
            )
        except ImportError:  # pragma: no cover - dependency is declared
            raise

        source = Path(path)
        try:
            reader = PdfReader(str(source))
        except OSError:
            raise
        except (FileNotDecryptedError, WrongPasswordError) as exc:
            raise PdfEncryptedError(
                f"{source}: PDF is encrypted"
            ) from exc
        except (PyPdfError, ValueError, TypeError) as exc:
            logger.debug("pypdf could not open %s: %s", source, exc)
            return PdfMetadata(page_count=0, metadata={})

        if getattr(reader, "is_encrypted", False):
            raise PdfEncryptedError(f"{source}: PDF is encrypted")

        page_count = 0
        try:
            page_count = len(reader.pages)
        except (PyPdfError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("pypdf page count failed for %s: %s", source, exc)

        metadata: dict[str, str] = {}
        try:
            raw_metadata = getattr(reader, "metadata", None)
            if raw_metadata is not None:
                for key, value in dict(raw_metadata).items():
                    name = str(key).lstrip("/")
                    if name and value is not None:
                        metadata[name] = str(value)
        except (PyPdfError, ValueError, TypeError, AttributeError) as exc:
            logger.debug("pypdf metadata failed for %s: %s", source, exc)

        return PdfMetadata(page_count=page_count, metadata=metadata)


class PdfStatementSource:
    """Acquire a PDF document using an injected metadata reader."""

    format = InputFormat.PDF

    def __init__(self, metadata_reader: PdfMetadataReader) -> None:
        self._metadata_reader = metadata_reader

    def acquire(self, path: Path) -> PdfDocument:
        """Return a not-yet-extracted :class:`PdfDocument` for *path*.

        Args:
            path: PDF file path.

        Returns:
            The document handle with page count and metadata.

        Raises:
            OSError: If the file cannot be read.
            PdfEncryptedError: If the PDF is encrypted.
        """
        source = Path(path)
        metadata = self._metadata_reader.read(source)
        return PdfDocument(
            path=source,
            page_count=metadata.page_count,
            metadata=metadata.metadata,
            source=SourceLocation(source, InputFormat.PDF),
        )
