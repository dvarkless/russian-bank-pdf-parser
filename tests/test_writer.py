"""Tests for the canonical CSV writer and its legacy facade."""

from __future__ import annotations

import codecs
import csv
import io
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bank_parser.adapters.writers import CanonicalCsvWriter
from bank_parser.domain.models import OperationType, Transaction
from bank_parser.errors import WriteError
from bank_parser.writers import HEADER, write_transactions


def _tx(
    day=1,
    merchant="Shop",
    amount="10.50",
    currency="RUB",
    category="Food",
    operation_type=OperationType.DEBIT,
    comment="",
) -> Transaction:
    return Transaction(
        date=date(2026, 5, day),
        merchant=merchant,
        amount=Decimal(amount),
        currency=currency,
        category=category,
        operation_type=operation_type,
        comment=comment,
    )


def test_writer_exact_bytes_header_bom_lf_and_8_fields(tmp_path):
    path = tmp_path / "out.csv"
    count = CanonicalCsvWriter().write(
        [_tx(), _tx(day=2, amount="0.00", operation_type=OperationType.CREDIT)],
        path,
    )
    assert count == 2
    data = path.read_bytes()
    assert data.startswith(codecs.BOM_UTF8)
    assert b"\r" not in data
    assert data.endswith(b"\n")
    lines = data.decode("utf-8-sig").splitlines()
    assert lines[0] == "date,merchant,amount,currency,category,type,comment,"
    assert len(lines) == 3
    assert lines[1].split(",") == [
        "01/05/2026", "Shop", "10.50", "RUB", "Food", "Списание", "", "",
    ]
    assert lines[2].split(",")[2] == "0.00"
    assert lines[2].split(",")[5] == "Пополнение"
    assert all(len(next(csv.reader([line]))) == 8 for line in lines)


def test_writer_uses_enum_value_not_str_enum_representation(tmp_path):
    path = tmp_path / "out.csv"
    CanonicalCsvWriter().write([_tx(operation_type=OperationType.CREDIT)], path)
    text = path.read_text(encoding="utf-8-sig")
    assert "Пополнение" in text
    assert "OperationType" not in text


def test_writer_formats_absolute_two_decimals(tmp_path):
    path = tmp_path / "out.csv"
    CanonicalCsvWriter().write([_tx(amount="900")], path)
    assert path.read_text(encoding="utf-8-sig").splitlines()[1].split(",")[2] == "900.00"


def test_writer_returns_zero_for_empty_iterable(tmp_path):
    path = tmp_path / "empty.csv"
    assert CanonicalCsvWriter().write([], path) == 0
    assert path.read_text(encoding="utf-8-sig").splitlines() == [
        "date,merchant,amount,currency,category,type,comment,"
    ]


def test_writer_rejects_more_than_two_decimal_places(tmp_path):
    path = tmp_path / "bad.csv"
    with pytest.raises(WriteError, match="at most 2 decimal places"):
        CanonicalCsvWriter().write([_tx(amount="1.005")], path)


def test_writer_rejects_non_decimal_amount(tmp_path):
    path = tmp_path / "bad.csv"
    tx = _tx()
    object.__setattr__(tx, "amount", 1.5)  # frozen dataclass bypass for negativity test
    with pytest.raises(WriteError, match="must be a Decimal"):
        CanonicalCsvWriter().write([tx], path)


def test_write_transactions_facade_and_header(tmp_path):
    path = tmp_path / "facade.csv"
    assert HEADER == [
        "date", "merchant", "amount", "currency", "category", "type",
        "comment", "",
    ]
    assert write_transactions([_tx()], path) == 1
    assert path.read_bytes().startswith(codecs.BOM_UTF8)


def test_write_transactions_accepts_legacy_string_operation_type(tmp_path):
    path = tmp_path / "legacy.csv"
    tx = Transaction(
        date(2026, 5, 1),
        "Shop",
        Decimal("10.00"),
        "RUB",
        "Food",
        "Списание",  # type: ignore[arg-type]
        "",
    )
    assert write_transactions([tx], path) == 1
    assert path.read_text(encoding="utf-8-sig").splitlines()[1].endswith(
        "Списание,,"
    )
