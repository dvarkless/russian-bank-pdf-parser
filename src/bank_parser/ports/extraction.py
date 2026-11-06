"""Port for PDF content extraction strategies."""

from __future__ import annotations

from typing import Protocol

from ..domain.raw import ExtractedDocument, PdfDocument

__all__ = ["PdfExtractor"]


class PdfExtractor(Protocol):
    """Extracts table rows or text lines from an acquired PDF document."""

    name: str

    def extract(self, document: PdfDocument) -> ExtractedDocument: ...
