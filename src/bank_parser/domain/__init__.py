"""Domain layer: pure value objects, raw containers and value parsers.

The domain layer imports only the standard library and :mod:`bank_parser.errors`
(which has no runtime project imports); it must never import pandas, pdfplumber,
pypdf or any adapter module.
"""

from __future__ import annotations

from .currency import CurrencyCode
from .models import (
    InputFormat,
    Money,
    OperationType,
    SourceLocation,
    Transaction,
)
from .parsing import RussianAmountParser, RussianDateParser
from .raw import (
    ColumnLayout,
    ExtractedDocument,
    NormalizedDocument,
    NormalizedTable,
    NormalizedText,
    PdfDocument,
    RawDocument,
    RawLine,
    RawRecord,
    RawRow,
    RawTable,
    RawText,
)

__all__ = [
    "ColumnLayout",
    "CurrencyCode",
    "ExtractedDocument",
    "InputFormat",
    "Money",
    "NormalizedDocument",
    "NormalizedTable",
    "NormalizedText",
    "OperationType",
    "PdfDocument",
    "RawDocument",
    "RawLine",
    "RawRecord",
    "RawRow",
    "RawTable",
    "RawText",
    "RussianAmountParser",
    "RussianDateParser",
    "SourceLocation",
    "Transaction",
]
