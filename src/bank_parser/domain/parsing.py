"""Pure, context-free parsers for Russian statement dates and amounts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

__all__ = ["RussianAmountParser", "RussianDateParser"]

_MINUS_SIGNS = "\u2212\u2013\u2014\u2012\u2015"
_CURRENCY_SYMBOLS = frozenset(
    "₽$€£¥₸₴₹₺₼₾¢"
)


class RussianDateParser:
    """Parse operation dates from Russian bank statements.

    The accepted layouts cover the fixtures (T-Bank timestamps, day-first dot
    dates and slash dates); no locale-dependent parsing is used.
    """

    DATE_FORMATS: tuple[str, ...] = (
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y",
        "%d/%m/%Y",
    )

    def parse(self, raw: str) -> date:
        """Parse *raw* into an operation date, dropping any time component.

        Args:
            raw: Date cell or line exactly as extracted from the statement.

        Returns:
            The operation date.

        Raises:
            ValueError: If *raw* matches none of :attr:`DATE_FORMATS`.
        """
        text = raw.strip() if isinstance(raw, str) else ""
        for date_format in self.DATE_FORMATS:
            try:
                return datetime.strptime(text, date_format).date()
            except ValueError:
                continue
        accepted = ", ".join(self.DATE_FORMATS)
        raise ValueError(
            f"cannot parse date {raw!r}; expected one of: {accepted}"
        )


class RussianAmountParser:
    """Parse signed amounts with the tolerances required by the fixtures."""

    MINUS_SIGNS: str = _MINUS_SIGNS
    """Unicode dash characters treated as a minus sign."""

    CURRENCY_SYMBOLS: frozenset[str] = _CURRENCY_SYMBOLS
    """Currency symbols/letters ignored while parsing an amount."""

    def parse(self, raw: str) -> Decimal:
        """Parse a signed amount into an exact :class:`~decimal.Decimal`.

        Accepts comma or dot decimals, unicode minus/dash variants, NBSP and
        thin-space thousands separators, optional currency symbols and an
        optional leading ``+``.  When both ``,`` and ``.`` appear, the
        right-most one is the decimal separator; the other is a thousands
        separator.

        Args:
            raw: Amount cell or line exactly as extracted from the statement.

        Returns:
            The signed amount, never a float and never rounded.

        Raises:
            ValueError: If *raw* does not contain a parsable decimal.
        """
        if not isinstance(raw, str):
            raise ValueError(
                f"cannot parse amount {raw!r}: expected a decimal amount"
            )

        characters: list[str] = []
        for character in raw.strip():
            if character.isspace():
                continue
            if character in self.MINUS_SIGNS:
                characters.append("-")
            elif character in self.CURRENCY_SYMBOLS:
                continue
            else:
                characters.append(character)
        cleaned = "".join(characters)

        if not cleaned:
            raise ValueError(f"cannot parse amount {raw!r}: no digits found")

        if "," in cleaned and "." in cleaned:
            if cleaned.rfind(",") > cleaned.rfind("."):
                cleaned = cleaned.replace(".", "").replace(",", ".")
            else:
                cleaned = cleaned.replace(",", "")
        elif "," in cleaned:
            cleaned = cleaned.replace(",", ".")

        try:
            value = Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(
                f"cannot parse amount {raw!r}: expected a decimal amount"
            ) from exc

        if not value.is_finite():
            raise ValueError(
                f"cannot parse amount {raw!r}: expected a finite decimal amount"
            )
        return value
