"""Registry of supported banks plus bank auto-detection helpers."""

from __future__ import annotations

import importlib
import re
from pathlib import Path
from typing import Callable

from ..models import Transaction
from ..readers import read_table

#: Canonical bank name -> parser module inside :mod:`bank_parser.banks`.
_REGISTRY: dict[str, str] = {
    "tbank": "tbank",
}

#: Accepted user-facing aliases (case-insensitive) for each supported bank.
_ALIASES: dict[str, str] = {
    "tbank": "tbank",
    "t-bank": "tbank",
    "т-банк": "tbank",
    "т банк": "tbank",
}

#: Filename fragments (lowercase, separators removed) that identify T-Bank.
_TBANK_FILENAME_MARKERS: tuple[str, ...] = ("tbank", "тбанк", "tбанк")

_TBANK_HEADER_MARKERS: tuple[str, ...] = ("Номер карты", "Дата операции")

SUPPORTED_BANKS: tuple[str, ...] = tuple(sorted(_REGISTRY))
"""Canonical names of the banks this build can parse."""


def supported_banks() -> list[str]:
    """Return the canonical names of supported banks."""
    return list(SUPPORTED_BANKS)


def _normalize_name(name: str) -> str:
    """Normalize a user-supplied bank name for alias lookup."""
    return " ".join(name.strip().lower().split())


def _load_parser_module(module_name: str):
    """Import a bank parser module lazily, with a clear error if unavailable."""
    try:
        return importlib.import_module(f".{module_name}", __name__)
    except ImportError as exc:  # pragma: no cover - only before the module lands
        raise ImportError(
            f"Parser module for bank {module_name!r} is not available: {exc}"
        ) from exc


def get_parser(name: str) -> Callable[[str | Path], list[Transaction]]:
    """Return the ``parse`` callable for the named bank.

    Args:
        name: Canonical bank name or one of its aliases (case-insensitive).

    Returns:
        A callable that takes a file path and returns a list of
        :class:`~bank_parser.models.Transaction`.

    Raises:
        ValueError: If *name* is empty or does not name a supported bank.
    """
    if not isinstance(name, str) or not _normalize_name(name):
        raise ValueError("Bank name must be a non-empty string.")

    key = _normalize_name(name)
    module_name = _ALIASES.get(key)
    if module_name is None:
        raise ValueError(
            f"Unsupported bank {name!r}. Supported banks: {', '.join(SUPPORTED_BANKS)} "
            "(aliases: t-bank, т-банк, т банк)."
        )
    module = _load_parser_module(module_name)
    return module.parse


def detect_bank(path: str | Path) -> str:
    """Detect the bank that produced *path*.

    T-Bank is detected when the file name contains ``t-bank``/``tbank``/
    ``т-банк``/``т банк`` (in any mixing of Latin and Cyrillic), or when the
    first row (the header) contains both ``Номер карты`` and ``Дата операции``.

    Args:
        path: Path to the export file.

    Returns:
        The canonical bank name, e.g. ``"tbank"``.

    Raises:
        FileNotFoundError: If *path* does not exist.
        ValueError: If the bank cannot be detected.
    """
    source = Path(path)

    compact_name = re.sub(r"[\s\-_.]+", "", source.stem.lower())
    if any(marker in compact_name for marker in _TBANK_FILENAME_MARKERS):
        return "tbank"

    rows = read_table(source)
    header = {cell.strip() for cell in rows[0]} if rows else set()
    if all(marker in header for marker in _TBANK_HEADER_MARKERS):
        return "tbank"

    raise ValueError(
        f"Could not detect the bank for {source}. "
        "Use --bank to select a supported bank explicitly "
        f"({', '.join(SUPPORTED_BANKS)})."
    )
