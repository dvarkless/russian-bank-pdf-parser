"""Exception hierarchy for the bank statement parser.

Every failure raised by the parser derives from :class:`BankParserError`.  The
:class:`ValueErrorCompat` branch additionally derives from :class:`ValueError`
so v1 callers keep catching legacy failures during the OOP migration; new code
should catch :class:`BankParserError`.

This module contains no I/O and imports no project module at runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Sequence

if TYPE_CHECKING:
    from pathlib import Path

    from .domain.models import SourceLocation

__all__ = [
    "AmountParseError",
    "BankParserError",
    "DateParseError",
    "DetectionError",
    "EncodingError",
    "ExtractionError",
    "InputError",
    "MissingHeaderError",
    "NoExtractableContentError",
    "NormalizationError",
    "ParseError",
    "PdfEncryptedError",
    "PdfOpenError",
    "UnsupportedBankError",
    "UnsupportedFormatError",
    "ValidationError",
    "ValueErrorCompat",
    "WriteError",
]

_MAX_RAW_VALUE_LENGTH = 120


def _excerpt(value: str) -> str:
    """Bound a raw value to the length allowed in error messages."""
    if len(value) <= _MAX_RAW_VALUE_LENGTH:
        return value
    return value[: _MAX_RAW_VALUE_LENGTH - 3] + "..."


class BankParserError(Exception):
    """Base class for every error raised by :mod:`bank_parser`."""


class ValueErrorCompat(BankParserError, ValueError):
    """Base for parser errors that v1 callers can catch as ``ValueError``."""


class InputError(ValueErrorCompat):
    """The input file cannot be read or interpreted as a statement."""


class EncodingError(InputError):
    """The input file could not be decoded with any supported encoding."""

    def __init__(self, path: str | Path, encodings: Sequence[str]) -> None:
        self.path = str(path)
        self.encodings = tuple(encodings)
        super().__init__(
            f"{self.path}: cannot decode input; tried encodings: "
            f"{', '.join(self.encodings)}"
        )


class UnsupportedFormatError(ValueErrorCompat):
    """The input path has a format no source can handle."""

    def __init__(
        self, path: str | Path, supported_formats: Sequence[str]
    ) -> None:
        self.path = str(path)
        self.supported_formats = tuple(supported_formats)
        super().__init__(
            f"{self.path}: unsupported input format; supported formats: "
            f"{', '.join(self.supported_formats)}"
        )


class UnsupportedBankError(ValueErrorCompat):
    """The requested bank name or alias is not registered."""

    def __init__(
        self,
        name: str,
        supported_banks: Sequence[str],
        *,
        hint: str = "",
    ) -> None:
        self.name = name
        self.supported_banks = tuple(supported_banks)
        self.hint = hint
        message = (
            f"Unsupported bank {name!r}. Supported banks: "
            f"{', '.join(self.supported_banks)}."
        )
        if hint:
            message = f"{message} {hint}"
        super().__init__(message)


class DetectionError(ValueErrorCompat):
    """The bank could not be detected, or candidate detections tied."""


class NormalizationError(ValueErrorCompat):
    """Raw extracted content cannot be normalised into a statement table."""


class MissingHeaderError(NormalizationError):
    """The table header lacks one or more required columns."""

    def __init__(
        self,
        *,
        location: SourceLocation,
        missing: Sequence[str],
        found: Sequence[str] = (),
    ) -> None:
        self.location = location
        self.missing = tuple(missing)
        self.found = tuple(found)
        quoted_missing = ", ".join(repr(name) for name in self.missing)
        quoted_found = (
            ", ".join(repr(name) for name in self.found)
            if self.found
            else "none"
        )
        super().__init__(
            f"{location.describe()}: missing required header(s): "
            f"{quoted_missing}; found: {quoted_found}"
        )


class ParseError(ValueErrorCompat):
    """A raw field could not be parsed into a domain value."""

    def __init__(
        self,
        *,
        location: SourceLocation,
        field: str,
        raw_value: str,
        expected: str,
    ) -> None:
        self.location = location
        self.field = field
        self.raw_value = _excerpt(raw_value)
        self.expected = expected
        super().__init__(
            f"{location.describe()}: cannot parse {field} "
            f"{self.raw_value!r}: expected {expected}"
        )


class DateParseError(ParseError):
    """An operation date could not be parsed."""

    def __init__(
        self,
        *,
        location: SourceLocation,
        raw_value: str,
        expected: str = "a date",
    ) -> None:
        super().__init__(
            location=location,
            field="date",
            raw_value=raw_value,
            expected=expected,
        )


class AmountParseError(ParseError):
    """An operation amount could not be parsed."""

    def __init__(
        self,
        *,
        location: SourceLocation,
        raw_value: str,
        expected: str = "a decimal amount",
    ) -> None:
        super().__init__(
            location=location,
            field="amount",
            raw_value=raw_value,
            expected=expected,
        )


class ValidationError(ValueErrorCompat):
    """Parsed transactions fail a semantic cross-check."""


class ExtractionError(BankParserError):
    """Content could not be extracted from a PDF statement."""


class PdfOpenError(ExtractionError):
    """A PDF file could not be opened."""


class PdfEncryptedError(ExtractionError):
    """A PDF file is encrypted and cannot be parsed."""


class NoExtractableContentError(ExtractionError):
    """A PDF contained no text or tables the parser can use."""


class WriteError(BankParserError):
    """The canonical CSV output could not be written."""
