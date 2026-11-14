"""Tests for the Ozon PDF table mapper and its ordered purpose rules."""

from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path

import pytest

from bank_parser.banks.ozon_pdf import OzonPdfMapper
from bank_parser.domain.models import OperationType
from bank_parser.domain.parsing import RussianAmountParser, RussianDateParser
from bank_parser.errors import ValidationError
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
        (
            "Выплата кешбека по программе лояльности за период с 05.09.2026 "
            "по 05.11.2026.",
            "+35,00", "Кешбэк", "", OperationType.CREDIT,
        ),
        (
            "Перевод A1 через СБП. Отправитель: Иван П. Без НДС.",
            "+500,00", "Перевод через СБП", "Иван П", OperationType.CREDIT,
        ),
        (
            "Размещение вклада по Договору NDEPFL6_1 от 2026-10-18. Без НДС.",
            "-100000,00", "Размещение вклада", "", OperationType.DEBIT,
        ),
        (
            "Возврат вклада в связи с досрочным расторжением договора по "
            "заявлению клиента. Без НДС.",
            "+159461,36", "Возврат вклада", "", OperationType.CREDIT,
        ),
        (
            "Возврат оплаты товаров по карте 1658 сумма 2.70 в DOSTAVKA IZ "
            "PYATEROCHK MOSCOW RU дата 2026-05-29 время 21:12:49",
            "+2,70", "Возврат оплаты товаров",
            "DOSTAVKA IZ PYATEROCHK MOSCOW RU", OperationType.CREDIT,
        ),
        (
            "Возврат оплаты за товары/услуги, купленные на Платформе Ozon, "
            "заказ № 90581427-0060. Без НДС.",
            "+677,00", "Возврат оплаты товаров/услуг на Платформе Ozon",
            "", OperationType.CREDIT,
        ),
        (
            "Перевод клиенту Банка. НДС не облагается.",
            "-10000,00", "Перевод клиенту Банка", "",
            OperationType.DEBIT,
        ),
        (
            "Платеж в пользу МТС, 9867148931. НДС не облагается",
            "-510,00", "Платеж в пользу МТС", "МТС", OperationType.DEBIT,
        ),
        (
            "Платеж в пользу ТСЖ ЙОРТ-2, 5356233957. НДС не облагается",
            "-5000,00", "Платеж в пользу ТСЖ", "ТСЖ ЙОРТ-2",
            OperationType.DEBIT,
        ),
        (
            "Снятие наличных денежных средств со счета 8125 сумма 10000.00 "
            "в банкомате ОЗОН Банка 111224 дата 2026-06-04 время 19:47:56",
            "-10000,00", "Снятие наличных", "ОЗОН Банк",
            OperationType.DEBIT,
        ),
        (
            "Зачисление по переводу денежных средств по карте 1658 сумма "
            "10000.00 из T-Bank Card2Card MOSCOW RU дата 2025-12-27",
            "+10000,00", "Зачисление по переводу", "T-Bank",
            OperationType.CREDIT,
        ),
        (
            "л/ с05111785100,Возв.ошиб. переч.суммы по п/п5от27.12.2025",
            "+164875,59", "Возврат ошибочного перевода", "",
            OperationType.CREDIT,
        ),
        (
            "166030074121// Сулейманова Диляра Ривгатовна//оплата "
            "задолженности по ИП № 66798/24/16006-ип от 13.08.2024",
            "-164875,59", "Оплата задолженности по ИП", "",
            OperationType.DEBIT,
        ),
        (
            "Неизвестное назначение платежа",
            "-1,00", "Прочие операции", "", OperationType.DEBIT,
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


def test_ozon_unknown_purpose_falls_back_to_other():
    tx = _mapper().map(_doc([_row("Неизвестное назначение платежа")]))[0]
    assert tx.category == "Прочие операции"
    assert tx.merchant == ""


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


def test_ozon_account_falls_back_to_bank_name_without_reader():
    tx = _mapper().map(
        _doc([_row("Перевод собственных средств. Без НДС.", "+100,00")])
    )[0]
    assert tx.account == "ozon"


def test_ozon_account_uses_reader_value():
    mapper = OzonPdfMapper(
        RussianDateParser(),
        RussianAmountParser(),
        currency="RUR",
        account_reader=lambda path: "40817810200015168125",
    )
    tx = mapper.map(
        _doc([_row("Перевод собственных средств. Без НДС.", "+100,00")])
    )[0]
    assert tx.account == "40817810200015168125"


@pytest.mark.skipif(
    not Path("data/input/ozon_2026.pdf").exists(),
    reason="real 2026 Ozon fixture is not present",
)
def test_ozon_2026_real_fixture_converts_all_operations(tmp_path):
    from bank_parser.cli import build_application

    output = tmp_path / "ozon_2026.csv"
    result = build_application().convert(
        Path("data/input/ozon_2026.pdf"), output
    )
    assert result.transactions_written == 734

    rows = list(csv.reader(output.open(encoding="utf-8-sig")))
    assert len(rows) - 1 == 734
    assert all(row[5] for row in rows[1:])
    credits = sum(
        Decimal(row[3]) for row in rows[1:] if row[6] == "Пополнение"
    )
    debits = sum(
        Decimal(row[3]) for row in rows[1:] if row[6] == "Списание"
    )
    assert credits == Decimal("1793473.90")
    assert debits == Decimal("1793438.90")
