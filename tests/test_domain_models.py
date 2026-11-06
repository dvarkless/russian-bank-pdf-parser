"""Tests for domain value objects: OperationType, Money, Transaction, SourceLocation."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from bank_parser.domain.models import (
    InputFormat,
    Money,
    OperationType,
    SourceLocation,
    Transaction,
)


@pytest.mark.parametrize(
    ("signed", "expected"),
    [
        (Decimal("100.00"), OperationType.CREDIT),
        (Decimal("0.01"), OperationType.CREDIT),
        (Decimal("0"), OperationType.DEBIT),
        (Decimal("-0.01"), OperationType.DEBIT),
        (Decimal("-900.00"), OperationType.DEBIT),
    ],
)
def test_operation_type_from_signed_amount(signed, expected):
    assert OperationType.from_signed_amount(signed) is expected


def test_operation_type_values_are_canonical_russian():
    assert OperationType.DEBIT.value == "Списание"
    assert OperationType.CREDIT.value == "Пополнение"
    assert OperationType.DEBIT == "Списание"


def test_money_sign_helpers_and_negation():
    money = Money(amount=Decimal("-900.00"), currency="RUB")
    assert money.absolute == Decimal("900.00")
    assert money.is_credit is False
    assert money.operation_type is OperationType.DEBIT
    assert (-money).amount == Decimal("900.00")
    assert (-money).is_credit is True


def test_money_is_frozen_and_slots():
    money = Money(amount=Decimal("1.00"), currency="RUR")
    assert money.currency == "RUR"
    with pytest.raises((AttributeError, TypeError)):
        money.amount = Decimal("2.00")  # type: ignore[misc]


@pytest.mark.parametrize("invalid", [1.5, True, 100, "1.00", None])
def test_money_rejects_non_decimal_amounts(invalid):
    with pytest.raises(ValueError, match="decimal.Decimal"):
        Money(amount=invalid, currency="RUB")  # type: ignore[arg-type]


def test_money_rejects_more_than_two_decimal_places():
    with pytest.raises(ValueError, match="at most 2 decimal places"):
        Money(amount=Decimal("1.005"), currency="RUB")


@pytest.mark.parametrize("invalid", [Decimal("NaN"), Decimal("Infinity")])
def test_money_rejects_non_finite_amounts(invalid):
    with pytest.raises(ValueError, match="finite"):
        Money(amount=invalid, currency="RUB")


def test_transaction_from_money_debit_and_credit():
    debit = Transaction.from_money(
        date=date(2026, 5, 1),
        merchant="Shop",
        money=Money(amount=Decimal("-42.50"), currency="RUB"),
        category="Food",
        comment="lunch",
    )
    assert debit.amount == Decimal("42.50")
    assert debit.operation_type is OperationType.DEBIT
    assert debit.currency == "RUB"
    assert debit.comment == "lunch"
    assert debit.location is None

    credit = Transaction.from_money(
        date=date(2026, 5, 2),
        merchant="Employer",
        money=Money(amount=Decimal("1000.00"), currency="RUR"),
        category="Salary",
    )
    assert credit.amount == Decimal("1000.00")
    assert credit.operation_type is OperationType.CREDIT


def test_transaction_from_money_zero_is_debit():
    tx = Transaction.from_money(
        date=date(2026, 5, 3),
        merchant="Zero",
        money=Money(amount=Decimal("0.00"), currency="RUB"),
        category="Other",
    )
    assert tx.amount == Decimal("0.00")
    assert tx.operation_type is OperationType.DEBIT


def test_transaction_location_default_and_positional_legacy_fields():
    tx = Transaction(
        date(2026, 5, 1),
        "Shop",
        Decimal("10.00"),
        "RUB",
        "Food",
        OperationType.DEBIT,
        "note",
    )
    assert tx.location is None
    assert tuple(tx.__dataclass_fields__) == (
        "date", "merchant", "amount", "currency", "category",
        "operation_type", "comment", "location",
    )


@pytest.mark.parametrize(
    ("kwargs", "text"),
    [
        ({}, "input.csv"),
        ({"page": 2}, "input.csv page 2"),
        ({"data_row": 5}, "input.csv data row 5"),
        ({"physical_row": 7}, "input.csv physical row 7"),
        ({"page": 2, "data_row": 5, "physical_row": 7},
         "input.csv page 2, data row 5, physical row 7"),
    ],
)
def test_source_location_describe(kwargs, text):
    location = SourceLocation(
        path=Path("input.csv"), format=InputFormat.CSV, **kwargs
    )
    assert location.describe() == text


def test_source_location_rejects_nonpositive_numbers():
    for name in ("page", "data_row", "physical_row"):
        with pytest.raises(ValueError, match=name):
            SourceLocation(
                path=Path("x"), format=InputFormat.CSV, **{name: 0}
            )
