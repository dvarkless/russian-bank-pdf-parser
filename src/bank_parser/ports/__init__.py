"""Ports layer: capability Protocols and the BankAdapter ABC.

Ports may import :mod:`bank_parser.domain` (and the dependency-free
:mod:`bank_parser.errors`); they must never import pandas, pdfplumber, pypdf or
concrete adapter modules at module load time.
"""

from __future__ import annotations

from .adapter import AdapterDependencies, BankAdapter
from .detection import Detection, DetectionContext
from .extraction import PdfExtractor
from .mapping import AmountParser, DateParser, RowMapper
from .pipeline import CanonicalWriter, InputNormalizer, StatementValidator
from .source import (
    CsvPeek,
    PdfMetadata,
    PdfMetadataReader,
    PdfPeek,
    StatementSource,
    TableReader,
)

__all__ = [
    "AdapterDependencies",
    "AmountParser",
    "BankAdapter",
    "CanonicalWriter",
    "CsvPeek",
    "DateParser",
    "Detection",
    "DetectionContext",
    "InputNormalizer",
    "PdfExtractor",
    "PdfMetadata",
    "PdfMetadataReader",
    "PdfPeek",
    "RowMapper",
    "StatementSource",
    "StatementValidator",
    "TableReader",
]
