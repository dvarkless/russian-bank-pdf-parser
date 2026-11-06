"""Sber CSV adapter — reuses the T-Bank 17-column row mapper.

The Sber CSV export (``data/input/Сбер_csv.csv``) has exactly the same
17-column Russian header and mapping as the T-Bank CSV export; only bank
metadata, canonical name and detection signals differ.  The mapper is therefore
reused unchanged, which is the reason :class:`TbankCsvMapper` lives in its own
module.
"""

from __future__ import annotations

from typing import ClassVar

from ..domain.models import InputFormat
from ..ports.adapter import BankAdapter
from ..ports.detection import Detection, DetectionContext
from ..ports.mapping import RowMapper
from .tbank_csv import TbankCsvMapper

__all__ = ["SberCsvAdapter"]


class SberCsvAdapter(BankAdapter):
    """Bank adapter for the Sber 17-column CSV export.

    Detection is filename-first because the header is byte-for-byte identical
    to the T-Bank CSV header (architecture A1): content alone cannot tell the
    two banks apart safely.  The generic header signature therefore scores 60,
    exactly like :class:`~bank_parser.banks.tbank_csv.TbankCsvAdapter`, so the
    registry raises a ``DetectionError`` for a neutral 17-column CSV instead of
    silently picking a bank.
    """

    name = "sber-csv"
    aliases = ("sber-csv", "sber", "сбер", "сбербанк")
    formats = frozenset({InputFormat.CSV})
    required_headers = ("Дата операции", "Сумма операции", "Описание")
    statement_currency = ""

    FILENAME_TOKENS: ClassVar[frozenset[str]] = frozenset(
        {"sber", "сбер", "sberbank", "сбербанк", "sbercsv", "сберcsv"}
    )
    HEADER_SIGNATURE: ClassVar[tuple[str, ...]] = (
        "Номер карты",
        "Дата операции",
        "Сумма операции",
        "Описание",
    )
    FILENAME_CONFIDENCE: ClassVar[int] = 90
    HEADER_CONFIDENCE: ClassVar[int] = 60

    @classmethod
    def probe(cls, ctx: DetectionContext) -> Detection | None:
        """Return a confidence-scored Sber CSV detection for *ctx*.

        Filename markers (``sber``/``сбер``/``сбербанк``, including the
        compacted mixed-script token produced for ``Сбер_csv``) score 90.  The
        generic 17-column Russian CSV header scores 60 because it is shared
        with the T-Bank CSV export.

        Args:
            ctx: Cached detection context with lazy filename/header signals.

        Returns:
            The detection, or ``None`` when no Sber CSV signal matches.
        """
        matched_tokens = sorted(cls.FILENAME_TOKENS & ctx.filename_tokens)
        if matched_tokens:
            return Detection(
                cls.name,
                cls.FILENAME_CONFIDENCE,
                f"filename contains {matched_tokens[0]!r}",
            )

        header = ctx.csv_header()
        if header:
            names = {
                cell.lstrip("\ufeff").strip()
                for cell in header
            }
            if all(marker in names for marker in cls.HEADER_SIGNATURE):
                return Detection(
                    cls.name,
                    cls.HEADER_CONFIDENCE,
                    "CSV header matches the generic 17-column Russian schema",
                )
        return None

    def create_mapper(self) -> RowMapper:
        """Return the shared T-Bank/Sber CSV mapper with injected parsers."""
        return TbankCsvMapper(self._deps.date_parser, self._deps.amount_parser)
