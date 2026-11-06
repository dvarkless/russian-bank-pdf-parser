"""Tests for TableNormalizer, TextNormalizer and DefaultStatementValidator."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from decimal import Decimal
from pathlib import Path
import re

import pytest

from bank_parser.adapters.normalizers import TableNormalizer, TextNormalizer
from bank_parser.adapters.validation import DefaultStatementValidator
from bank_parser.domain.models import InputFormat, OperationType, SourceLocation, Transaction
from bank_parser.domain.raw import RawText
from bank_parser.errors import MissingHeaderError, NormalizationError, ValidationError
from helpers import make_normalized_table, make_raw_table, make_raw_text


def test_table_normalizer_resolves_layout_records_and_locations():
    document = make_raw_table(
        [["id", "name"], ["1", "alpha"], ["2", "beta"]]
    )
    normalized = TableNormalizer(required_headers=("name",)).normalize(document)
    assert normalized.layout.headers == ("id", "name")
    assert [record.cells for record in normalized.records] == [
        ("1", "alpha"), ("2", "beta")
    ]
    assert normalized.records[0].location.data_row == 1
    assert normalized.records[1].location.data_row == 2
    assert normalized.records[0].location.physical_row == 2


def test_table_normalizer_finds_header_after_leading_furniture():
    document = make_raw_table(
        [["statement title"], ["date", "amount"], ["01.05.2026", "10,00"]]
    )
    normalized = TableNormalizer(required_headers=("date", "amount")).normalize(document)
    assert normalized.layout.headers == ("date", "amount")
    assert [record.cells for record in normalized.records] == [
        ("01.05.2026", "10,00")
    ]
    assert normalized.records[0].location.physical_row == 3


def test_table_normalizer_skips_blank_rows_and_numbers_data_rows_after_filtering():
    document = make_raw_table(
        [
            ["date", "amount"],
            ["", ""],
            ["01.05.2026", "10,00"],
            ["  ", ""],
            ["02.05.2026", "20,00"],
        ]
    )
    normalized = TableNormalizer(required_headers=("date",)).normalize(document)
    assert len(normalized.records) == 2
    assert [record.location.data_row for record in normalized.records] == [1, 2]
    assert [record.location.physical_row for record in normalized.records] == [3, 5]


def test_table_normalizer_record_predicate_filters_and_numbers_after_predicate():
    document = make_raw_table(
        [
            ["date", "amount"],
            ["01.05.2026", "10,00"],
            ["header repeat", ""],
            ["02.05.2026", "20,00"],
        ]
    )
    normalized = TableNormalizer(
        required_headers=("date",),
        record_predicate=lambda row: row.cells[0].startswith("0"),
    ).normalize(document)
    assert [record.cells[0] for record in normalized.records] == [
        "01.05.2026", "02.05.2026"
    ]
    assert [record.location.data_row for record in normalized.records] == [1, 2]


def test_table_normalizer_missing_required_header():
    document = make_raw_table([["date", "amount"], ["1", "2"]])
    with pytest.raises(MissingHeaderError, match="comment"):
        TableNormalizer(required_headers=("date", "comment")).normalize(document)


def test_table_normalizer_rejects_raw_text():
    raw = make_raw_text([(1, "line")])
    with pytest.raises(NormalizationError, match="expected a raw table"):
        TableNormalizer(required_headers=("date",)).normalize(raw)


def test_text_normalizer_skips_patterns_and_preserves_locations():
    raw = make_raw_text(
        [(1, "page header"), (1, "keep one"), (2, "page footer"), (2, "keep two")]
    )
    normalized = TextNormalizer(
        skip_patterns=(re.compile(r"^page "),)
    ).normalize(raw)
    assert [line.text for line in normalized.lines] == ["keep one", "keep two"]
    assert [(line.page, line.line) for line in normalized.lines] == [
        (1, 2), (2, 4)
    ]


def test_text_normalizer_rejects_raw_table():
    table = make_raw_table([["h"]])
    with pytest.raises(NormalizationError, match="expected raw text"):
        TextNormalizer().normalize(table)


def _tx(**overrides):
    base = dict(
        date=date(2026, 5, 1),
        merchant="Shop",
        amount=Decimal("10.00"),
        currency="RUB",
        category="Food",
        operation_type=OperationType.DEBIT,
        comment="",
    )
    base.update(overrides)
    return Transaction(**base)


def _document():
    return make_normalized_table(
        [["01.05.2026", "10.00"]], ("date", "amount")
    )


def test_validator_accepts_valid_transactions():
    DefaultStatementValidator().validate(_document(), [_tx(), _tx(amount=Decimal("0.00"))])


def test_validator_rejects_negative_amount():
    with pytest.raises(ValidationError, match="absolute value"):
        DefaultStatementValidator().validate(
            _document(), [_tx(amount=Decimal("-1.00"))]
        )


def test_validator_rejects_more_than_two_decimal_places():
    with pytest.raises(ValidationError, match="more than 2 decimal"):
        DefaultStatementValidator().validate(
            _document(), [_tx(amount=Decimal("1.005"))]
        )


def test_validator_rejects_non_enum_operation_type():
    with pytest.raises(ValidationError, match="OperationType"):
        DefaultStatementValidator().validate(
            _document(), [replace(_tx(), operation_type="Списание")]  # type: ignore[arg-type]
        )


def test_validator_rejects_non_transaction():
    with pytest.raises(ValidationError, match="is not a Transaction"):
        DefaultStatementValidator().validate(_document(), [object()])  # type: ignore[list-item]
