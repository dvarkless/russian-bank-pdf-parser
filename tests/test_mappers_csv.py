"""Tests for the T-Bank / Sber CSV / Alfa CSV mappers."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from bank_parser.adapters.normalizers import TableNormalizer
from bank_parser.adapters.validation import DefaultStatementValidator
from bank_parser.banks.alfa_csv import AlfaCsvMapper
from bank_parser.banks.sber_csv import SberCsvAdapter
from bank_parser.banks.tbank_csv import TbankCsvMapper
from bank_parser.domain.models import OperationType
from bank_parser.domain.parsing import RussianAmountParser, RussianDateParser
from bank_parser.errors import AmountParseError, DateParseError, MissingHeaderError, ParseError
from bank_parser.ports.adapter import AdapterDependencies
from helpers import make_raw_table

DATE = RussianDateParser()
AMOUNT = RussianAmountParser()

TBANK_HEADER = [
    "Имя счёта", "Номер карты", "Дата операции", "Сумма операции",
    "Валюта операции", "Сумма в валюте счёта", "Валюта счёта", "Статус",
    "Категория по-умолчанию", "Ваша категория", "MCC", "Описание",
    "Сообщение", "Округление", "Сумма операции с округлением",
    "Бонусы (включая кэшбэк)", "Учёт в аналитике",
]

ALFA_HEADER = [
    "operationDate", "transactionDate", "accountName", "accountNumber",
    "cardName", "cardNumber", "merchant", "amount", "currency", "status",
    "category", "mcc", "type", "comment", "bonusValue", "bonusTitle",
]


def _row(header, values):
    row = [""] * len(header)
    index = {name: position for position, name in enumerate(header)}
    for name, value in values.items():
        row[index[name]] = value
    return row


def _tbank_row(values):
    return _row(TBANK_HEADER, values)


def _alfa_row(values):
    return _row(ALFA_HEADER, values)


def _normalize(rows, header, required):
    return TableNormalizer(required_headers=required).normalize(
        make_raw_table([header, *rows])
    )


def _tbank_mapper():
    return TbankCsvMapper(DATE, AMOUNT)


def test_tbank_mapper_sign_type_and_amount():
    rows = [
        _tbank_row({
            "Дата операции": "30.04.2026 23:23:49",
            "Сумма операции": "-900,00",
            "Описание": "Дмитрий Щ.",
            "Валюта операции": "RUB",
            "Категория по-умолчанию": "Переводы",
            "Сообщение": "note",
        }),
        _tbank_row({
            "Дата операции": "29.04.2026",
            "Сумма операции": "+7000,00",
            "Описание": "Salary",
            "Валюта операции": "RUB",
            "Категория по-умолчанию": "Доходы",
        }),
        _tbank_row({
            "Дата операции": "28.04.2026",
            "Сумма операции": "0",
            "Описание": "Zero",
            "Валюта операции": "RUB",
            "Категория по-умолчанию": "Прочее",
        }),
    ]
    txs = _tbank_mapper().map(
        _normalize(rows, TBANK_HEADER, TbankCsvMapper.REQUIRED_HEADERS)
    )
    assert [tx.amount for tx in txs] == [
        Decimal("900.00"), Decimal("7000.00"), Decimal("0.00")
    ]
    assert [tx.operation_type for tx in txs] == [
        OperationType.DEBIT, OperationType.CREDIT, OperationType.DEBIT
    ]
    assert txs[0].merchant == "Дмитрий Щ."
    assert txs[0].comment == "note"


def test_tbank_mapper_currency_and_category_fallbacks():
    row = _tbank_row({
        "Дата операции": "01.05.2026",
        "Сумма операции": "-100,00",
        "Описание": "Fallback",
        "Валюта операции": "",
        "Валюта счёта": "USD",
        "Категория по-умолчанию": "",
        "Ваша категория": "Своя",
    })
    tx = _tbank_mapper().map(
        _normalize([row], TBANK_HEADER, TbankCsvMapper.REQUIRED_HEADERS)
    )[0]
    assert tx.currency == "USD"
    assert tx.category == "Своя"


def test_tbank_mapper_resolves_columns_by_header_name_not_position():
    reordered = list(reversed(TBANK_HEADER))
    row = _row(reordered, {
        "Дата операции": "01.05.2026",
        "Сумма операции": "-100,00",
        "Описание": "Reordered",
        "Валюта операции": "RUB",
        "Категория по-умолчанию": "Food",
    })
    tx = _tbank_mapper().map(
        _normalize([row], reordered, TbankCsvMapper.REQUIRED_HEADERS)
    )[0]
    assert tx.merchant == "Reordered"
    assert tx.category == "Food"


def test_tbank_mapper_bad_date_error_has_row_number():
    row = _tbank_row({
        "Дата операции": "31.02.2026", "Сумма операции": "-1,00",
        "Описание": "Bad date",
    })
    with pytest.raises(DateParseError, match="data row 1"):
        _tbank_mapper().map(
            _normalize([row], TBANK_HEADER, TbankCsvMapper.REQUIRED_HEADERS)
        )


def test_tbank_mapper_bad_amount_error_has_row_number():
    rows = [
        _tbank_row({"Дата операции": "01.05.2026", "Сумма операции": "-1,00",
                    "Описание": "ok"}),
        _tbank_row({"Дата операции": "02.05.2026", "Сумма операции": "abc",
                    "Описание": "bad"}),
    ]
    with pytest.raises(AmountParseError, match="data row 2"):
        _tbank_mapper().map(
            _normalize(rows, TBANK_HEADER, TbankCsvMapper.REQUIRED_HEADERS)
        )


def test_sber_csv_adapter_metadata_and_shared_mapper():
    deps = AdapterDependencies(
        date_parser=DATE, amount_parser=AMOUNT,
        validator=DefaultStatementValidator(),
    )
    adapter = SberCsvAdapter(deps)
    assert adapter.name == "sber-csv"
    assert "sber" in adapter.aliases
    row = _tbank_row({
        "Дата операции": "01.05.2026", "Сумма операции": "-10,00",
        "Описание": "Sber", "Валюта операции": "RUB",
        "Категория по-умолчанию": "Food",
    })
    normalized = _normalize([row], TBANK_HEADER, TbankCsvMapper.REQUIRED_HEADERS)
    assert adapter.create_mapper().map(normalized) == _tbank_mapper().map(normalized)


def test_alfa_mapper_uses_operation_date_not_transaction_date():
    rows = [
        _alfa_row({
            "operationDate": "01.11.2026", "transactionDate": "02.11.2026",
            "merchant": "Shop", "amount": "100", "currency": "RUR",
            "status": "Выполнен", "category": "Food", "type": "Списание",
        }),
        _alfa_row({
            "operationDate": "", "transactionDate": "03.11.2026",
            "merchant": "Fallback", "amount": "200", "currency": "RUR",
            "status": "В обработке", "category": "Food", "type": "Списание",
        }),
    ]
    txs = AlfaCsvMapper(DATE, AMOUNT).map(
        _normalize(rows, ALFA_HEADER, AlfaCsvMapper.REQUIRED_HEADERS)
    )
    assert [tx.date.isoformat() for tx in txs] == ["2026-11-01", "2026-11-03"]
    assert [tx.amount for tx in txs] == [Decimal("100.00"), Decimal("200.00")]


def test_alfa_mapper_explicit_type_is_authoritative_for_zero_amount():
    rows = [
        _alfa_row({
            "operationDate": "01.11.2026", "merchant": "Credit",
            "amount": "0", "currency": "RUR", "type": "Пополнение",
        }),
        _alfa_row({
            "operationDate": "02.11.2026", "merchant": "Debit",
            "amount": "0", "currency": "RUR", "type": "Списание",
        }),
    ]
    txs = AlfaCsvMapper(DATE, AMOUNT).map(
        _normalize(rows, ALFA_HEADER, AlfaCsvMapper.REQUIRED_HEADERS)
    )
    assert txs[0].operation_type is OperationType.CREDIT
    assert txs[1].operation_type is OperationType.DEBIT
    assert [tx.amount for tx in txs] == [Decimal("0.00"), Decimal("0.00")]


def test_alfa_mapper_ignores_status_and_preserves_rur():
    statuses = ["Выполнен", "В обработке", "", "Неизвестный статус"]
    rows = [
        _alfa_row({
            "operationDate": f"0{index + 1}.11.2026", "merchant": f"M{index}",
            "amount": "10", "currency": "RUR", "type": "Списание",
            "status": status,
        })
        for index, status in enumerate(statuses)
    ]
    txs = AlfaCsvMapper(DATE, AMOUNT).map(
        _normalize(rows, ALFA_HEADER, AlfaCsvMapper.REQUIRED_HEADERS)
    )
    assert len(txs) == 4
    assert {tx.currency for tx in txs} == {"RUR"}
    assert [tx.merchant for tx in txs] == ["M0", "M1", "M2", "M3"]


def test_alfa_mapper_unknown_type_raises_parse_error_with_row():
    row = _alfa_row({
        "operationDate": "01.11.2026", "merchant": "Bad",
        "amount": "10", "currency": "RUR", "type": "Перевод",
    })
    with pytest.raises(ParseError, match="data row 1") as excinfo:
        AlfaCsvMapper(DATE, AMOUNT).map(
            _normalize([row], ALFA_HEADER, AlfaCsvMapper.REQUIRED_HEADERS)
        )
    assert "type" in str(excinfo.value)


def test_alfa_mapper_missing_required_header():
    header = [name for name in ALFA_HEADER if name != "type"]
    row = _row(header, {
        "operationDate": "01.11.2026", "merchant": "No type",
        "amount": "10", "currency": "RUR",
    })
    with pytest.raises(MissingHeaderError, match="'type'"):
        AlfaCsvMapper(DATE, AMOUNT).map(
            _normalize([row], header, AlfaCsvMapper.REQUIRED_HEADERS)
        )
