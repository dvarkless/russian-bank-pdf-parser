"""The :class:`BankAdapter` ABC and its injected dependencies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from ..domain.models import InputFormat
from .detection import Detection, DetectionContext
from .extraction import PdfExtractor
from .mapping import AmountParser, DateParser, RowMapper
from .pipeline import InputNormalizer, StatementValidator

__all__ = ["AdapterDependencies", "BankAdapter"]


@dataclass(frozen=True, slots=True)
class AdapterDependencies:
    """Collaborators shared by all bank adapters.

    Attributes:
        date_parser: Context-free date parser.
        amount_parser: Context-free amount parser.
        validator: Statement validator.
    """

    date_parser: DateParser
    amount_parser: AmountParser
    validator: StatementValidator


class BankAdapter(ABC):
    """Base class for bank-specific adapters.

    Adapters are classes, not instances in the registry: metadata and
    :meth:`probe` are class-level, while parsing collaborators are
    constructor-injected by the adapter factory.
    """

    name: ClassVar[str]
    aliases: ClassVar[tuple[str, ...]]
    formats: ClassVar[frozenset[InputFormat]]
    required_headers: ClassVar[tuple[str, ...]] = ()
    statement_currency: ClassVar[str] = ""

    def __init__(self, deps: AdapterDependencies) -> None:
        self._deps = deps

    @classmethod
    @abstractmethod
    def probe(cls, ctx: DetectionContext) -> Detection | None:
        """Return a confidence-scored match for this adapter, or ``None``."""

    @abstractmethod
    def create_mapper(self) -> RowMapper:
        """Return a new mapper for this bank."""

    def create_extractor(self) -> PdfExtractor | None:
        """Return a configured PDF extractor, or ``None`` for CSV adapters."""
        return None

    def create_normalizer(self) -> InputNormalizer:
        """Return the default table normaliser for this adapter.

        PDF adapters override this with a record predicate or a text
        normaliser.  The adapter import is deliberately lazy so the ports
        layer stays free of adapter imports at module load time.
        """
        from ..adapters.normalizers import TableNormalizer

        return TableNormalizer(
            required_headers=self.required_headers,
        )
