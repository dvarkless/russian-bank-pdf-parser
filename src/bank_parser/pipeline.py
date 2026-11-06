"""Statement pipeline: the fixed acquire→extract→normalize→map→write flow."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .domain.models import Transaction
from .domain.raw import (
    ExtractedDocument,
    NormalizedDocument,
    PdfDocument,
    RawDocument,
    RawTable,
)
from .errors import ExtractionError, NormalizationError
from .ports.extraction import PdfExtractor
from .ports.mapping import RowMapper
from .ports.pipeline import CanonicalWriter, InputNormalizer, StatementValidator
from .ports.source import StatementSource

__all__ = [
    "CsvPipeline",
    "PdfPipeline",
    "PipelineResult",
    "StatementPipeline",
]


@dataclass(frozen=True, slots=True)
class PipelineResult:
    """Summary of one successful pipeline run.

    Attributes:
        bank: Canonical bank name that handled the statement.
        input_path: Input file path.
        output_path: Canonical CSV path written.
        transactions_written: Number of data rows written.
    """

    bank: str
    input_path: Path
    output_path: Path
    transactions_written: int


class StatementPipeline(ABC):
    """Template Method for converting one statement into canonical CSV.

    Subclasses only vary :meth:`_extract` (CSV identity versus PDF extraction);
    all stage ordering, validation placement and writer use are fixed here.
    """

    def __init__(
        self,
        *,
        bank_name: str,
        source: StatementSource,
        normalizer: InputNormalizer,
        mapper: RowMapper,
        validator: StatementValidator,
        writer: CanonicalWriter,
    ) -> None:
        self._bank_name = bank_name
        self._source = source
        self._normalizer = normalizer
        self._mapper = mapper
        self._validator = validator
        self._writer = writer

    def read(self, input_path: Path) -> list[Transaction]:
        """Run acquire → extract → normalize → map → validate.

        Args:
            input_path: Statement file path.

        Returns:
            Mapped transactions in input order.

        Raises:
            BankParserError: When acquisition, extraction, normalisation,
                mapping or validation fails.
        """
        raw = self._acquire(Path(input_path))
        extracted = self._extract(raw)
        normalized = self._normalize(extracted)
        transactions = self._map(normalized)
        self._validate(normalized, transactions)
        return transactions

    def run(self, input_path: Path, output_path: Path) -> PipelineResult:
        """Convert *input_path* and write the canonical CSV to *output_path*.

        Args:
            input_path: Statement file path.
            output_path: Destination canonical CSV path.

        Returns:
            The pipeline summary.

        Raises:
            BankParserError: When any pipeline stage fails.
            OSError: When the input cannot be read or the output cannot be
                written (the writer wraps output failures as ``WriteError``).
        """
        transactions = self.read(Path(input_path))
        written = self._write(transactions, Path(output_path))
        return PipelineResult(
            bank=self._bank_name,
            input_path=Path(input_path),
            output_path=Path(output_path),
            transactions_written=written,
        )

    def _acquire(self, path: Path) -> RawDocument:
        """Acquire the raw document through the injected source."""
        return self._source.acquire(path)

    @abstractmethod
    def _extract(self, raw: RawDocument) -> ExtractedDocument:
        """Extract table rows or text lines from the acquired document."""

    def _normalize(self, extracted: ExtractedDocument) -> NormalizedDocument:
        """Normalise the extracted document."""
        return self._normalizer.normalize(extracted)

    def _map(self, normalized: NormalizedDocument) -> list[Transaction]:
        """Map the normalised document to canonical transactions."""
        return self._mapper.map(normalized)

    def _validate(
        self,
        normalized: NormalizedDocument,
        transactions: Sequence[Transaction],
    ) -> None:
        """Validate mapped transactions against domain invariants."""
        self._validator.validate(normalized, transactions)

    def _write(
        self, transactions: Sequence[Transaction], path: Path
    ) -> int:
        """Write canonical transactions and return the data-row count."""
        return self._writer.write(transactions, path)


class CsvPipeline(StatementPipeline):
    """Pipeline whose source already produces a raw table."""

    def _extract(self, raw: RawDocument) -> ExtractedDocument:
        """Return the CSV raw table unchanged."""
        if not isinstance(raw, RawTable):
            raise NormalizationError(
                f"{self._bank_name}: expected a raw table from the CSV "
                f"source, got {type(raw).__name__}"
            )
        return raw


class PdfPipeline(StatementPipeline):
    """Pipeline that delegates extraction to an injected PDF strategy."""

    def __init__(
        self,
        *,
        bank_name: str,
        source: StatementSource,
        extractor: PdfExtractor,
        normalizer: InputNormalizer,
        mapper: RowMapper,
        validator: StatementValidator,
        writer: CanonicalWriter,
    ) -> None:
        super().__init__(
            bank_name=bank_name,
            source=source,
            normalizer=normalizer,
            mapper=mapper,
            validator=validator,
            writer=writer,
        )
        self._extractor = extractor

    def _extract(self, raw: RawDocument) -> ExtractedDocument:
        """Extract table/text content from the acquired PDF."""
        if not isinstance(raw, PdfDocument):
            raise ExtractionError(
                f"{self._bank_name}: expected a PDF document, got "
                f"{type(raw).__name__}"
            )
        return self._extractor.extract(raw)
