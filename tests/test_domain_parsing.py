"""Tests for the pure Russian date and amount parsers."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from bank_parser.domain.parsing import RussianAmountParser, RussianDateParser


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("30.04.2026 23:23:49", date(2026, 4, 30)),
        ("30.04.2026", date(2026, 4, 30)),
        ("30/04/2026", date(2026, 4, 30)),
        (" 01.01.2030  ", date(2030, 1, 1)),
    ],
)
def test_russian_date_parser_formats(raw, expected):
    assert RussianDateParser().parse(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "not-a-date", "2026-04-30", "31.02.2026", "30.13.2026"],
)
def test_russian_date_parser_rejects_invalid(raw):
    with pytest.raises(ValueError, match="cannot parse date"):
        RussianDateParser().parse(raw)


def test_russian_date_parser_rejects_non_string():
    with pytest.raises(ValueError):
        RussianDateParser().parse(None)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("-900,00", Decimal("-900.00")),
        ("-900.00", Decimal("-900.00")),
        ("\u2212900,00", Decimal("-900.00")),
        ("\u2013900,00", Decimal("-900.00")),
        ("1 234,56", Decimal("1234.56")),
        ("1\u00a0234,56", Decimal("1234.56")),
        ("1\u202f234,56", Decimal("1234.56")),
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("+250,50 \u20bd", Decimal("250.50")),
        ("0", Decimal("0")),
        ("900", Decimal("900")),
    ],
)
def test_russian_amount_parser_variants(raw, expected):
    assert RussianAmountParser().parse(raw) == expected


@pytest.mark.parametrize("raw", ["", "abc", "12,3,4", " ", "--"])
def test_russian_amount_parser_rejects_unparseable(raw):
    with pytest.raises(ValueError, match="cannot parse amount"):
        RussianAmountParser().parse(raw)


def test_russian_amount_parser_rejects_non_string():
    with pytest.raises(ValueError, match="cannot parse amount"):
        RussianAmountParser().parse(100)  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", ["NaN", "Infinity", "-Infinity"])
def test_russian_amount_parser_rejects_non_finite(raw):
    with pytest.raises(ValueError):
        RussianAmountParser().parse(raw)
