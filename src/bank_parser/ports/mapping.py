"""Ports for mapping normalised documents and parsing raw values."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Protocol

from ..domain.models import Transaction
from ..domain.raw import NormalizedDocument

__all__ = ["AmountParser", "DateParser", "RowMapper"]


class RowMapper(Protocol):
    """Maps a normalised statement document to canonical transactions."""

    def map(self, document: NormalizedDocument) -> list[Transaction]: ...


class DateParser(Protocol):
    """Parses a raw operation date without source context."""

    def parse(self, raw: str) -> date: ...


class AmountParser(Protocol):
    """Parses a raw signed amount without source context."""

    def parse(self, raw: str) -> Decimal: ...
