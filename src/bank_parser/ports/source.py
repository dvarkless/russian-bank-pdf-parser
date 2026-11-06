"""Ports for acquiring raw statements and reading tables."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..domain.models import InputFormat
from ..domain.raw import RawDocument, RawTable

__all__ = [
    "CsvPeek",
    "PdfMetadata",
    "PdfMetadataReader",
    "PdfPeek",
    "StatementSource",
    "TableReader",
]


@dataclass(frozen=True, slots=True)
class PdfMetadata:
    """Page count and best-effort metadata read from a PDF.

    Attributes:
        page_count: Number of pages, or ``0`` when unknown.
        metadata: Normalised document metadata; may be empty.
    """

    page_count: int
    metadata: Mapping[str, str]


class StatementSource(Protocol):
    """Turns an input path into a raw document for the pipeline."""

    format: InputFormat

    def acquire(self, path: Path) -> RawDocument: ...


class TableReader(Protocol):
    """Reads a CSV export into a :class:`~bank_parser.domain.raw.RawTable`."""

    def read(self, path: Path) -> RawTable: ...


class PdfMetadataReader(Protocol):
    """Reads a PDF's page count and metadata without extracting content."""

    def read(self, path: Path) -> PdfMetadata: ...


class CsvPeek(Protocol):
    """Cheap CSV signal access used by bank detection."""

    def header(self, path: Path) -> tuple[str, ...] | None: ...


class PdfPeek(Protocol):
    """Cheap PDF signal access used by bank detection."""

    def first_page_text(self, path: Path) -> str | None: ...

    def metadata(self, path: Path) -> Mapping[str, str]: ...
