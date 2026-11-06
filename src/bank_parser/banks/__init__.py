"""Supported-bank registry plus v1 compatibility facades.

New code should build an :class:`~bank_parser.application.Application` through
``bank_parser.cli.build_application``.  The legacy functions here keep the v1
surface (``get_parser``, ``detect_bank``, ``supported_banks``) while delegating
to the OOP registry and application.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from ..domain.models import Transaction
from ..ports.adapter import BankAdapter
from .tbank_csv import TbankCsvAdapter

__all__ = [
    "BANK_ADAPTERS",
    "SUPPORTED_BANKS",
    "build_registry",
    "detect_bank",
    "get_parser",
    "supported_banks",
]

#: Canonical adapter classes, in deterministic registration/detection order.
BANK_ADAPTERS: tuple[type[BankAdapter], ...] = (TbankCsvAdapter,)

#: Canonical names of the banks this build can parse.
SUPPORTED_BANKS: tuple[str, ...] = tuple(
    sorted(adapter.name for adapter in BANK_ADAPTERS)
)


def supported_banks() -> list[str]:
    """Return the canonical names of supported banks."""
    return list(SUPPORTED_BANKS)


def build_registry():
    """Build the bank registry from :data:`BANK_ADAPTERS`.

    Returns:
        A new :class:`~bank_parser.registry.BankRegistry` instance.
    """
    from ..registry import BankRegistry

    return BankRegistry(BANK_ADAPTERS)


def get_parser(
    name: str,
) -> Callable[[str | Path], list[Transaction]]:
    """Return a legacy path-to-transactions callable for a bank.

    Args:
        name: Canonical bank name or alias (case-insensitive).

    Returns:
        A callable that reads a statement and returns its transactions.

    Raises:
        UnsupportedBankError: If *name* is empty or not a supported bank.
        OSError: From the returned callable when the input cannot be read.
    """
    registry = build_registry()
    registry.resolve_alias(name)

    def parse(path: str | Path) -> list[Transaction]:
        from ..cli import build_application

        application = build_application()
        return application.read_transactions(Path(path), bank=name)

    return parse


def detect_bank(path: str | Path) -> str:
    """Detect the canonical bank name that produced *path*.

    Args:
        path: Input statement path.

    Returns:
        The canonical bank name, e.g. ``"tbank"``.

    Raises:
        FileNotFoundError: If *path* does not exist.
        UnsupportedFormatError: If the suffix is not ``.csv`` or ``.pdf``.
        DetectionError: If the bank cannot be detected or detection ties.
    """
    from ..adapters.csv_source import PandasTableReader
    from ..adapters.peeks import PandasCsvPeek, PdfPlumberPdfPeek
    from ..ports.detection import DetectionContext

    source = Path(path)
    context = DetectionContext(
        source,
        csv_peek=PandasCsvPeek(PandasTableReader()),
        pdf_peek=PdfPlumberPdfPeek(),
    )
    return build_registry().detect(context).name
