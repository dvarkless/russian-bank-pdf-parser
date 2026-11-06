"""Tests for the Sber PDF header/description line state machine."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bank_parser.adapters.normalizers import TextNormalizer
from bank_parser.banks.sber_pdf import SberPdfMapper
from bank_parser.domain.models import OperationType
from bank_parser.domain.parsing import RussianAmountParser, RussianDateParser
from bank_parser.errors import ParseError
from helpers import make_raw_text

HEADER = "05.11.2026 09:15 Прочие операции +107 841,00 112 031,82"
DESCRIPTION = (
    "05.11.2026 521757 Заработная плата. Операция по счету ****5685"
)


def _normalized(lines):
    return TextNormalizer().normalize(make_raw_text(lines))


def _mapper():
    return SberPdfMapper(RussianDateParser(), RussianAmountParser())


def test_sber_pdf_valid_header_description_plus_credit():
    txs = _mapper().map(_normalized([(1, HEADER), (1, DESCRIPTION)]))
    assert len(txs) == 1
    tx = txs[0]
    assert tx.date.isoformat() == "2026-11-05"
    assert tx.operation_type is OperationType.CREDIT
    assert tx.amount == Decimal("107841.00")
    assert tx.currency == "RUR"
    assert tx.category == "Прочие операции"
    assert tx.merchant == "Заработная плата"
    assert tx.comment == ""
    assert tx.location.page == 1
    assert tx.location.physical_row == 2


def test_sber_pdf_uses_operation_date_not_processing_date():
    header = "29.10.2026 10:02 Транспорт 46,00 36 914,45"
    description = "30.10.2026 804274 TRANSKART.RU KAZAN RUS. Операция по карте ****5838"
    tx = _mapper().map(_normalized([(1, header), (1, description)]))[0]
    assert tx.date.isoformat() == "2026-10-29"


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("46,00", OperationType.DEBIT),
        ("-46,00", OperationType.DEBIT),
        ("+46,00", OperationType.CREDIT),
    ],
)
def test_sber_pdf_sign_rule(amount, expected):
    header = f"05.11.2026 09:15 Транспорт {amount} 36 914,45"
    description = "05.11.2026 804274 TRANSKART.RU KAZAN RUS. Операция по карте ****5838"
    tx = _mapper().map(_normalized([(1, header), (1, description)]))[0]
    assert tx.operation_type is expected
    assert tx.amount == Decimal("46.00")


@pytest.mark.parametrize(
    "description",
    [
        "05.11.2026 521757 SBOL. Операция по счету ****5685",
        "05.11.2026 521757 SBOL перевод на платежный счет.. Операция по счету",
        "05.11.2026 521757 SP_LOTUS. KAZAN RUS. Операция по карте ****5838",
    ],
)
def test_sber_pdf_strips_operation_suffix(description):
    tx = _mapper().map(_normalized([(1, HEADER), (1, description)]))[0]
    assert "****" not in tx.merchant
    assert "Операция по" not in tx.merchant
    assert tx.merchant


def test_sber_pdf_ignores_furniture_and_continuation_lines():
    tx = _mapper().map(
        _normalized(
            [(1, HEADER), (1, "****5685"), (1, "Продолжение на следующей странице"),
             (1, DESCRIPTION)]
        )
    )[0]
    assert tx.merchant == "Заработная плата"


def test_sber_pdf_header_followed_by_header_is_error():
    with pytest.raises(ParseError, match="expected a description line") as excinfo:
        _mapper().map(
            _normalized(
                [(1, HEADER), (1, "05.11.2026 10:00 Транспорт 46,00 100,00")]
            )
        )
    assert "page 1" in str(excinfo.value)


def test_sber_pdf_eof_after_header_is_error():
    with pytest.raises(ParseError, match="expected a description line") as excinfo:
        _mapper().map(_normalized([(1, HEADER)]))
    assert "page 1" in str(excinfo.value)


@pytest.mark.parametrize(
    "description",
    [
        "05.11.2026 521757",
        "05.11.2026 521757 ...",
    ],
)
def test_sber_pdf_missing_or_empty_merchant_is_error(description):
    with pytest.raises(ParseError, match="non-empty merchant") as excinfo:
        _mapper().map(_normalized([(1, HEADER), (1, description)]))
    assert "page 1" in str(excinfo.value)


def test_sber_pdf_keeps_page_and_line_for_descriptions():
    tx = _mapper().map(
        _normalized([(1, "furniture"), (2, HEADER), (2, DESCRIPTION)])
    )[0]
    assert tx.location.page == 2
    assert tx.location.physical_row == 3
