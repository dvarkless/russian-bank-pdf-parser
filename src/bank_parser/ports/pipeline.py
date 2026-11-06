"""Ports for normalisation, validation and canonical writing."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Protocol

from ..domain.models import Transaction
from ..domain.raw import ExtractedDocument, NormalizedDocument

__all__ = ["CanonicalWriter", "InputNormalizer", "StatementValidator"]


class InputNormalizer(Protocol):
    """Turns an extracted document into a normalised document."""

    def normalize(self, document: ExtractedDocument) -> NormalizedDocument: ...


class StatementValidator(Protocol):
    """Cross-checks mapped transactions against the normalised document."""

    def validate(
        self,
        document: NormalizedDocument,
        transactions: Sequence[Transaction],
    ) -> None: ...


class CanonicalWriter(Protocol):
    """Writes canonical transactions to a CSV file and returns the row count."""

    def write(
        self, transactions: Iterable[Transaction], path: Path
    ) -> int: ...
