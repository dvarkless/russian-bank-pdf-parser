"""Recognise currency codes in source strings without converting them."""

from __future__ import annotations

import re

__all__ = ["CurrencyCode"]

_RUBLE_WORDS = frozenset(
    {
        "российский рубль",
        "российского рубля",
        "рубль",
        "рубля",
        "рублей",
        "руб",
    }
)

_SYMBOL_CODES: dict[str, str] = {
    "₽": "RUR",
    "$": "USD",
    "€": "EUR",
    "£": "GBP",
    "¥": "JPY",
    "₸": "KZT",
    "₴": "UAH",
    "₹": "INR",
    "₺": "TRY",
    "₼": "AZN",
    "₾": "GEL",
}

_CODE_RE = re.compile(r"[A-Za-z]{3}")


class CurrencyCode:
    """Map source currency spellings to codes, never converting between them.

    Explicit three-letter codes are preserved exactly: ``"RUB"`` stays ``"RUB"``
    and ``"RUR"`` stays ``"RUR"``.  Russian ruble words and the ``₽`` symbol map
    to the statement-level ``"RUR"`` code used by the PDF fixtures; other known
    symbols map to their code.
    """

    RUBLE_CODES: frozenset[str] = frozenset({"RUB", "RUR"})
    """Codes that mean Russian rubles in the supported statements."""

    @classmethod
    def from_source(cls, raw: str) -> str:
        """Return the currency code reported by *raw*.

        Args:
            raw: Currency cell or statement text exactly as extracted.

        Returns:
            The upper-case currency code, or ``""`` when *raw* is blank or the
            spelling is not recognised.
        """
        text = raw.strip() if isinstance(raw, str) else ""
        if not text:
            return ""
        if text in _SYMBOL_CODES:
            return _SYMBOL_CODES[text]
        if _CODE_RE.fullmatch(text):
            return text.upper()
        normalised = " ".join(text.lower().replace(".", " ").split())
        if normalised in _RUBLE_WORDS:
            return "RUR"
        return ""

    @classmethod
    def is_ruble(cls, raw: str) -> bool:
        """Return True when *raw* reports a Russian ruble code or spelling."""
        return cls.from_source(raw) in cls.RUBLE_CODES
