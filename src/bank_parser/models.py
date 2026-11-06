"""Canonical data model shared by readers, writers and bank parsers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Transaction:
    """One bank transaction in canonical form.

    Attributes:
        date: Operation date.
        merchant: Merchant / operation description.
        amount: Absolute operation amount as a ``Decimal`` (never a float).
        currency: Operation currency code, e.g. ``"RUB"``.
        category: Category assigned by the bank.
        operation_type: ``"Списание"`` (debit) or ``"Пополнение"`` (credit).
        comment: Free-form comment from the bank export; may be empty.
    """

    date: date
    merchant: str
    amount: Decimal
    currency: str
    category: str
    operation_type: str
    comment: str
