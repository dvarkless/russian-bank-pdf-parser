"""Detection value object and the lazy context adapters probe with.

:class:`DetectionContext` performs no I/O itself; it delegates to the injected
:class:`~bank_parser.ports.source.CsvPeek` /
:class:`~bank_parser.ports.source.PdfPeek` ports and caches each signal.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ..domain.models import InputFormat
from ..errors import UnsupportedFormatError
from .source import CsvPeek, PdfPeek

__all__ = ["Detection", "DetectionContext"]

_SUFFIX_FORMATS: dict[str, InputFormat] = {
    ".csv": InputFormat.CSV,
    ".pdf": InputFormat.PDF,
}
_SUPPORTED_SUFFIXES: tuple[str, ...] = (".csv", ".pdf")
_TOKEN_SPLIT_RE = re.compile(r"[\W_]+")


@dataclass(frozen=True, slots=True)
class Detection:
    """A single adapter's confidence-scored detection result.

    Attributes:
        adapter_name: Canonical name of the matching adapter.
        confidence: Deterministic score in ``0..100``.
        reason: Short human-readable explanation, e.g.
            ``"filename contains 'ozon'"``.
    """

    adapter_name: str
    confidence: int
    reason: str

    def __post_init__(self) -> None:
        if not self.adapter_name:
            raise ValueError("Detection.adapter_name must not be empty")
        if not 0 <= self.confidence <= 100:
            raise ValueError(
                "Detection.confidence must be between 0 and 100, got "
                f"{self.confidence}"
            )


def _tokenize_stem(stem: str) -> frozenset[str]:
    """Return lowercase filename tokens plus their compacted concatenation."""
    tokens = [
        token for token in _TOKEN_SPLIT_RE.split(stem.lower()) if token
    ]
    compact = "".join(tokens)
    if compact:
        tokens.append(compact)
    return frozenset(tokens)


class DetectionContext:
    """Lazy, cached signal access shared by every adapter probe.

    Args:
        path: Input path being detected.
        csv_peek: Cheap CSV header access port.
        pdf_peek: Cheap PDF text/metadata access port.
    """

    def __init__(
        self, path: Path, *, csv_peek: CsvPeek, pdf_peek: PdfPeek
    ) -> None:
        self._path = Path(path)
        self._csv_peek = csv_peek
        self._pdf_peek = pdf_peek
        self._filename_tokens = _tokenize_stem(self._path.stem)
        self._csv_header: tuple[str, ...] | None = None
        self._csv_header_loaded = False
        self._pdf_first_page_text: str | None = None
        self._pdf_first_page_text_loaded = False
        self._pdf_metadata: Mapping[str, str] | None = None
        self._pdf_metadata_loaded = False

    @property
    def path(self) -> Path:
        """Input path being detected."""
        return self._path

    @property
    def format(self) -> InputFormat:
        """Input format derived from the lowercase path suffix.

        Raises:
            UnsupportedFormatError: When the suffix is not ``.csv`` or ``.pdf``.
        """
        suffix = self._path.suffix.lower()
        try:
            return _SUFFIX_FORMATS[suffix]
        except KeyError:
            raise UnsupportedFormatError(
                self._path, _SUPPORTED_SUFFIXES
            ) from None

    @property
    def filename_tokens(self) -> frozenset[str]:
        """Lowercase stem tokens plus the compacted stem as one token."""
        return self._filename_tokens

    def csv_header(self) -> tuple[str, ...] | None:
        """Return the CSV header row, or ``None`` when it cannot be read."""
        if not self._csv_header_loaded:
            self._csv_header = self._csv_peek.header(self._path)
            self._csv_header_loaded = True
        return self._csv_header

    def pdf_first_page_text(self) -> str | None:
        """Return the first page's text, or ``None`` when unavailable."""
        if not self._pdf_first_page_text_loaded:
            self._pdf_first_page_text = self._pdf_peek.first_page_text(
                self._path
            )
            self._pdf_first_page_text_loaded = True
        return self._pdf_first_page_text

    def pdf_metadata(self) -> Mapping[str, str]:
        """Return PDF metadata, cached after the first read."""
        if not self._pdf_metadata_loaded:
            self._pdf_metadata = self._pdf_peek.metadata(self._path)
            self._pdf_metadata_loaded = True
        return self._pdf_metadata if self._pdf_metadata is not None else {}
