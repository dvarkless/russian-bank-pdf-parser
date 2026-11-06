"""Application facade: bank statement conversion use cases."""

from __future__ import annotations

from pathlib import Path

from .domain.models import Transaction
from .pipeline import PipelineResult
from .registry import AdapterFactory

__all__ = ["Application"]


class Application:
    """Thin use-case facade over :class:`AdapterFactory`."""

    def __init__(self, factory: AdapterFactory) -> None:
        self._factory = factory

    def convert(
        self,
        input_path: Path,
        output_path: Path,
        *,
        bank: str | None = None,
    ) -> PipelineResult:
        """Convert *input_path* into the canonical CSV at *output_path*.

        Args:
            input_path: Statement file path.
            output_path: Destination canonical CSV path.
            bank: Explicit bank name/alias; auto-detected when ``None``.

        Returns:
            The pipeline summary.

        Raises:
            BankParserError: When selection, acquisition, extraction,
                normalisation, mapping, validation or writing fails.
            OSError: When the input cannot be read.
        """
        _, pipeline = self._factory.create(
            path=Path(input_path), bank=bank
        )
        return pipeline.run(
            Path(input_path), Path(output_path)
        )

    def read_transactions(
        self,
        input_path: Path,
        *,
        bank: str | None = None,
    ) -> list[Transaction]:
        """Read *input_path* and return transactions without writing output.

        Args:
            input_path: Statement file path.
            bank: Explicit bank name/alias; auto-detected when ``None``.

        Returns:
            Mapped transactions in input order.

        Raises:
            BankParserError: When selection, acquisition, extraction,
                normalisation, mapping or validation fails.
            OSError: When the input cannot be read.
        """
        _, pipeline = self._factory.create(
            path=Path(input_path), bank=bank
        )
        return pipeline.read(Path(input_path))
