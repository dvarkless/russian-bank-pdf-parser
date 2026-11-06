"""Bank registry, source/pipeline factories and confidence-scored detection."""

from __future__ import annotations

import logging
from collections.abc import Iterable
from pathlib import Path

from .domain.models import InputFormat
from .errors import (
    BankParserError,
    DetectionError,
    UnsupportedBankError,
    UnsupportedFormatError,
)
from .pipeline import CsvPipeline, PdfPipeline, StatementPipeline
from .ports.adapter import AdapterDependencies, BankAdapter
from .ports.detection import Detection, DetectionContext
from .ports.pipeline import CanonicalWriter, StatementValidator
from .ports.source import CsvPeek, PdfPeek, StatementSource

__all__ = [
    "AdapterFactory",
    "BankRegistry",
    "CSV_HEADER_CONFIDENCE",
    "FILENAME_CONFIDENCE",
    "GENERIC_HEADER_CONFIDENCE",
    "PDF_BODY_CONFIDENCE",
    "PipelineFactory",
    "SourceFactory",
    "WEAK_CONFIDENCE",
]

logger = logging.getLogger(__name__)

#: Deterministic confidence bands used by adapter probes.
FILENAME_CONFIDENCE = 90
PDF_BODY_CONFIDENCE = 85
CSV_HEADER_CONFIDENCE = 70
GENERIC_HEADER_CONFIDENCE = 60
WEAK_CONFIDENCE = 50

_SUPPORTED_SUFFIXES: tuple[str, ...] = (".csv", ".pdf")


def _normalize_alias(name: str) -> str:
    """Normalise a user-facing bank name for alias lookup."""
    return " ".join(name.strip().lower().split())


class SourceFactory:
    """Select the source adapter for a path's suffix."""

    def __init__(
        self, *, csv: StatementSource, pdf: StatementSource
    ) -> None:
        self._csv = csv
        self._pdf = pdf

    def format_for_path(self, path: Path) -> InputFormat:
        """Return the input format implied by *path*'s suffix.

        Args:
            path: Input file path.

        Returns:
            :attr:`InputFormat.CSV` or :attr:`InputFormat.PDF`.

        Raises:
            UnsupportedFormatError: When the suffix is not a supported format.
        """
        suffix = Path(path).suffix.lower()
        if suffix == ".csv":
            return InputFormat.CSV
        if suffix == ".pdf":
            return InputFormat.PDF
        raise UnsupportedFormatError(path, _SUPPORTED_SUFFIXES)

    def for_path(self, path: Path) -> StatementSource:
        """Return the source for *path*.

        Args:
            path: Input file path.

        Returns:
            The CSV or PDF source adapter.

        Raises:
            UnsupportedFormatError: When the suffix is not supported.
        """
        source_format = self.format_for_path(path)
        return (
            self._csv
            if source_format is InputFormat.CSV
            else self._pdf
        )


class PipelineFactory:
    """Wire a bank adapter to a source, normaliser, mapper and writer."""

    def __init__(
        self,
        *,
        source_factory: SourceFactory,
        writer: CanonicalWriter,
        validator: StatementValidator,
    ) -> None:
        self._source_factory = source_factory
        self._writer = writer
        self._validator = validator

    def format_for_path(self, path: Path) -> InputFormat:
        """Return the format implied by *path*."""
        return self._source_factory.format_for_path(path)

    def build(
        self, adapter: BankAdapter, path: Path
    ) -> StatementPipeline:
        """Create a configured pipeline for *adapter* and *path*.

        Args:
            adapter: Instantiated bank adapter.
            path: Input path used to select the source.

        Returns:
            A CSV or PDF pipeline wired with the adapter's collaborators.

        Raises:
            UnsupportedFormatError: When the adapter does not support the
                path's format.
        """
        source = self._source_factory.for_path(path)
        if source.format not in adapter.formats:
            supported = tuple(
                sorted(source_format.value for source_format in adapter.formats)
            )
            raise UnsupportedFormatError(path, supported)

        normalizer = adapter.create_normalizer()
        mapper = adapter.create_mapper()
        extractor = adapter.create_extractor()
        if extractor is None:
            return CsvPipeline(
                bank_name=adapter.name,
                source=source,
                normalizer=normalizer,
                mapper=mapper,
                validator=self._validator,
                writer=self._writer,
            )
        return PdfPipeline(
            bank_name=adapter.name,
            source=source,
            extractor=extractor,
            normalizer=normalizer,
            mapper=mapper,
            validator=self._validator,
            writer=self._writer,
        )


class BankRegistry:
    """Resolve bank aliases and detect the adapter for an input path."""

    def __init__(
        self, adapters: Iterable[type[BankAdapter]]
    ) -> None:
        self._adapters = tuple(adapters)
        self._alias_map: dict[str, tuple[type[BankAdapter], ...]] = {}
        for adapter in self._adapters:
            if not isinstance(adapter, type) or not issubclass(
                adapter, BankAdapter
            ):
                raise TypeError(
                    "BankRegistry expects BankAdapter subclasses, got "
                    f"{adapter!r}"
                )
            aliases = {_normalize_alias(adapter.name)}
            aliases.update(
                _normalize_alias(alias) for alias in adapter.aliases
            )
            for alias in aliases:
                existing = self._alias_map.get(alias, ())
                if adapter not in existing:
                    self._alias_map[alias] = existing + (adapter,)

    @property
    def supported(self) -> tuple[str, ...]:
        """Canonical names of registered banks, sorted for stable output."""
        return tuple(sorted({adapter.name for adapter in self._adapters}))

    def _alias_hint(self) -> str:
        """Return a deterministic supported-alias hint for error messages."""
        return f"(aliases: {', '.join(sorted(self._alias_map))})"

    def resolve_alias(
        self,
        name: str,
        *,
        format: InputFormat | None = None,
    ) -> type[BankAdapter]:
        """Return the adapter class for a user-facing bank name or alias.

        Args:
            name: Canonical bank name or alias.
            format: Optional input format used to disambiguate aliases shared
                by a CSV and a PDF adapter.

        Returns:
            The matching adapter class.

        Raises:
            UnsupportedBankError: When the name is empty, unknown, unavailable
                for *format*, or ambiguous without a format.
        """
        if not isinstance(name, str) or not _normalize_alias(name):
            raise UnsupportedBankError(
                str(name),
                self.supported,
                hint="Bank name must be a non-empty string.",
            )

        key = _normalize_alias(name)
        candidates = self._alias_map.get(key)
        if not candidates:
            raise UnsupportedBankError(
                name, self.supported, hint=self._alias_hint()
            )

        if format is not None:
            candidates = tuple(
                adapter
                for adapter in candidates
                if format in adapter.formats
            )
            if not candidates:
                raise UnsupportedBankError(
                    name,
                    self.supported,
                    hint=(
                        f"Input format {format.value!r} is not supported by "
                        f"bank {name!r}. {self._alias_hint()}"
                    ),
                )

        if len(candidates) > 1:
            names = ", ".join(sorted(adapter.name for adapter in candidates))
            raise UnsupportedBankError(
                name,
                self.supported,
                hint=(
                    f"Alias {name!r} is ambiguous for multiple formats "
                    f"({names}); choose a file with a .csv or .pdf suffix."
                ),
            )
        return candidates[0]

    def candidates(
        self, fmt: InputFormat
    ) -> tuple[type[BankAdapter], ...]:
        """Return adapter classes that support *fmt* in registration order."""
        return tuple(
            adapter
            for adapter in self._adapters
            if fmt in adapter.formats
        )

    def detect(self, ctx: DetectionContext) -> type[BankAdapter]:
        """Return the adapter whose probe wins for *ctx*.

        Args:
            ctx: Lazy detection context for the input path.

        Returns:
            The matching adapter class.

        Raises:
            DetectionError: When nothing matches or the top confidence ties.
        """
        detections: list[
            tuple[type[BankAdapter], Detection]
        ] = []
        for adapter in self.candidates(ctx.format):
            try:
                detection = adapter.probe(ctx)
            except BankParserError as exc:
                logger.debug(
                    "probe for %s failed on %s: %s",
                    adapter.name,
                    ctx.path,
                    exc,
                )
                continue
            if detection is not None:
                detections.append((adapter, detection))

        if not detections:
            candidates = ", ".join(
                adapter.name for adapter in self.candidates(ctx.format)
            )
            raise DetectionError(
                f"Could not detect the bank for {ctx.path}. "
                f"Supported {ctx.format.value!r} input: "
                f"{candidates or 'none'}. Use --bank to select one explicitly."
            )

        best_confidence = max(
            detection.confidence for _, detection in detections
        )
        top = [
            (adapter, detection)
            for adapter, detection in detections
            if detection.confidence == best_confidence
        ]
        if len(top) > 1:
            names = ", ".join(
                sorted(adapter.name for adapter, _ in top)
            )
            raise DetectionError(
                f"Could not detect the bank for {ctx.path}: detection is "
                f"ambiguous at confidence {best_confidence}: {names}. "
                "Use --bank to select one explicitly."
            )
        return top[0][0]


class AdapterFactory:
    """Create an instantiated adapter and its wired pipeline."""

    def __init__(
        self,
        registry: BankRegistry,
        *,
        deps: AdapterDependencies,
        pipeline_factory: PipelineFactory,
        csv_peek: CsvPeek,
        pdf_peek: PdfPeek,
    ) -> None:
        self._registry = registry
        self._deps = deps
        self._pipeline_factory = pipeline_factory
        self._csv_peek = csv_peek
        self._pdf_peek = pdf_peek

    def create(
        self, *, path: Path, bank: str | None
    ) -> tuple[BankAdapter, StatementPipeline]:
        """Create the adapter and pipeline for *path*.

        Args:
            path: Input path.
            bank: Explicit bank name/alias; auto-detected when ``None``.

        Returns:
            The instantiated adapter and its configured pipeline.

        Raises:
            UnsupportedFormatError: When the path suffix is unsupported.
            UnsupportedBankError: When *bank* cannot be resolved.
            DetectionError: When auto-detection fails or ties.
        """
        target = Path(path)
        source_format = self._pipeline_factory.format_for_path(target)
        if bank is not None:
            adapter_class = self._registry.resolve_alias(
                bank, format=source_format
            )
        else:
            context = DetectionContext(
                target,
                csv_peek=self._csv_peek,
                pdf_peek=self._pdf_peek,
            )
            adapter_class = self._registry.detect(context)

        adapter = adapter_class(self._deps)
        pipeline = self._pipeline_factory.build(adapter, target)
        return adapter, pipeline
