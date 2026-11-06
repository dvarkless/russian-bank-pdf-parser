"""Tests for the Ozon PDF table mapper and its five purpose rules."""

from __future__ import annotations

from decimal import Decimal

import pytest

from bank_parser.banks.ozon_pdf import OzonPdfMapper
from bank_parser.domain.models import OperationType
from bank_parser.domain.parsing import RussianAmountParser, RussianDateParser
from bank_parser.errors import ParseError, ValidationError
from helpers import make_normalized_table

HEADER = (
    "Дата операции", "Документ", "Назначение платежа",
    "Сумма операции", "Валюта",
)


def _mapper():
    return OzonPdfMapper(RussianDateParser(), RussianAmountParser(), currency="RUR")


def _doc(rows):
    return make_normalized_table(rows, HEADER)


def _row(purpose, amount="-10,00", date="01.01.2026 10:00:00"):
    return [date, "doc", purpose, amount, amount]


@pytest.mark.parametrize(
    ("purpose", "amount", "category", "merchant", "op_type"),
    [
        (
            "Перевод через СБП. Получатель: Иван П. Без НДС.",
            "-500,00", "Перевод через СБП", "Иван П", OperationType.DEBIT,
        ),
        (
            "Перевод собственных средств. Без НДС.",
            "+1000,00", "Перевод собственных средств", "", OperationType.CREDIT,
        ),
        (
            "Оплата товаров/услуг на Платформе Ozon (Ozon Premium), заказ",
            "-199,00", "Оплата товаров/услуг на Платформе Ozon",
            "(Ozon Premium)", OperationType.DEBIT,
        ),
        (
            "Оплата товаров/услуг на Платформе Ozon, заказ",
            "-480,00", "Оплата товаров/услуг на Платформе Ozon",
            "", OperationType.DEBIT,
        ),
        (
            "Оплата товаров по карте 1658 сумма 10.00 в SHOP NAME Kazan RU "
            "дата 2026-01-03 время 12:00:00",
            "-10,00", "Оплата товаров", "SHOP NAME Kazan RU",
            OperationType.DEBIT,
        ),
        (
            "Чаевые по заказу № 1 от 01.01.2026. Без НДС.",
            "-10,00", "Чаевые по заказу", "", OperationType.DEBIT,
        ),
    ],
)
def test_ozon_purpose_rules(purpose, amount, category, merchant, op_type):
    tx = _mapper().map(_doc([_row(purpose, amount)]))[0]
    assert tx.category == category
    assert tx.merchant == merchant
    assert tx.operation_type is op_type
    assert tx.currency == "RUR"
    assert tx.comment == ""
    assert isinstance(tx.amount, Decimal)


def test_ozon_crlf_and_whitespace_normalization():
    purpose = (
        "Перевод\r\nсобственных   средств.\r\nБез НДС."
    )
    tx = _mapper().map(_doc([_row(purpose, "+250,00")]))[0]
    assert tx.category == "Перевод собственных средств"
    assert tx.merchant == ""
    assert tx.operation_type is OperationType.CREDIT


def test_ozon_unknown_purpose_raises_parse_error_with_location():
    with pytest.raises(ParseError, match="purpose") as excinfo:
        _mapper().map(_doc([_row("Неизвестное назначение платежа")]))
    assert "page 1" in str(excinfo.value)


def test_ozon_amount_columns_mismatch_raises_validation_error():
    row = ["01.01.2026 10:00:00", "doc", "Перевод собственных средств",
           "-100,00", "-100,01"]
    with pytest.raises(ValidationError, match="amount columns disagree") as excinfo:
        _mapper().map(_doc([row]))
    assert "page 1" in str(excinfo.value)


def test_ozon_preserves_order_currency_and_comments():
    rows = [
        _row("Перевод собственных средств. Без НДС.", "+100,00",
             "01.01.2026 10:00:00"),
        _row("Оплата товаров по карте 1 сумма 2.00 в A дата 2026-01-01",
             "-2,00", "02.01.2026 11:00:00"),
        _row("Чаевые по заказу № 3. Без НДС.", "-3,00",
             "03.01.2026 12:00:00"),
    ]
    txs = _mapper().map(_doc(rows))
    assert [tx.amount for tx in txs] == [
        Decimal("100.00"), Decimal("2.00"), Decimal("3.00")
    ]
    assert [tx.category for tx in txs] == [
        "Перевод собственных средств", "Оплата товаров", "Чаевые по заказу"
    ]
    assert [tx.date.isoformat() for tx in txs] == [
        "2026-01-01", "2026-01-02", "2026-01-03"
    ]
    assert {tx.currency for tx in txs} == {"RUR"}
    assert {tx.comment for tx in txs} == {""}
