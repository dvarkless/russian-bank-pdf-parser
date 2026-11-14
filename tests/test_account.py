"""Account-column detection tests against the real ``data/input`` fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from bank_parser.cli import build_application

#: Expected account value(s) per fixture.  Alfa resolves a single file-level
#: account (the first card name) applied to every row.
FIXTURE_ACCOUNTS = {
    "T-Банк.csv": {"Black"},
    "Сбер_csv.csv": {"Платёжный счёт"},
    "Альфа.CSV": {"Альфа-карта МИР"},
    "Ozon.pdf": {"40817810200015168125"},
    "Сбер.pdf": {"МИР Сберкарта •• 5838"},
    "ozon_2026.pdf": {"40817810200015168125"},
    "ozon_2026_deposit.pdf": {"40817810400015170997"},
}


@pytest.mark.skipif(
    not all((Path("data/input") / name).exists() for name in FIXTURE_ACCOUNTS),
    reason="real data/input fixtures are not present",
)
@pytest.mark.parametrize("filename,expected", sorted(FIXTURE_ACCOUNTS.items()))
def test_account_value_per_fixture(filename, expected):
    app = build_application()
    transactions = app.read_transactions(Path("data/input") / filename)
    assert transactions
    assert {tx.account for tx in transactions} == expected
