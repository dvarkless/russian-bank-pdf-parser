"""End-to-end tests for the ``--detect-bank`` flag and optional ``-o/--output``."""

from __future__ import annotations

import codecs
import re
from pathlib import Path

import pytest

from bank_parser.cli import main

CANONICAL_HEADER = "account,date,merchant,amount,currency,category,type,comment,"
DEFAULT_FILENAME_RE = re.compile(
    r"^(?:tbank|alfa|ozon|sber)_\d{8}_\d{6}\.csv$"
)

#: Real fixtures mapped to their canonical ``adapter.name``.
FIXTURE_BANKS = {
    "T-Банк.csv": "tbank",
    "Сбер_csv.csv": "tbank",
    "Альфа.CSV": "alfa",
    "Ozon.pdf": "ozon",
    "Сбер.pdf": "sber",
}


def _write_inline_tbank(path: Path) -> None:
    path.write_text(
        "Дата операции;Сумма операции;Описание\n"
        "01.05.2026 10:00:00;-100,00;Shop\n"
        "02.05.2026;+250,50;Employer\n",
        encoding="utf-8",
        newline="",
    )


def _write_unknown_csv(path: Path) -> None:
    path.write_text("foo;bar\n1;2\n", encoding="utf-8", newline="")


def _assert_canonical_csv(path: Path, expected_transactions: int) -> None:
    """Assert a generated file follows the canonical CSV contract."""
    data = path.read_bytes()
    assert data.startswith(codecs.BOM_UTF8)
    assert b"\r" not in data
    rows = path.read_text(encoding="utf-8-sig").splitlines()
    assert rows[0] == CANONICAL_HEADER
    assert len(rows) == expected_transactions + 1
    for row in rows[1:]:
        fields = row.split(",")
        assert len(fields) == 9
        assert fields[0] != ""
        assert fields[8] == ""
        assert re.fullmatch(r"\d{2}/\d{2}/\d{4}", fields[1])
        assert re.fullmatch(r"\d+\.\d{2}", fields[3])
        assert fields[6] in ("Списание", "Пополнение")


@pytest.mark.skipif(
    not all((Path("data/input") / name).exists() for name in FIXTURE_BANKS),
    reason="real data/input fixtures are not present",
)
@pytest.mark.parametrize("filename,expected", list(FIXTURE_BANKS.items()))
def test_cli_detect_bank_prints_canonical_name(filename, expected, capsys):
    exit_code = main(["-i", str(Path("data/input") / filename), "--detect-bank"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == expected
    assert captured.err == ""


def test_cli_detect_bank_does_not_convert_or_write(tmp_path, monkeypatch, capsys):
    source = tmp_path / "tbank.csv"
    _write_inline_tbank(source)
    monkeypatch.chdir(tmp_path)
    exit_code = main(["-i", str(source), "--detect-bank"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == "tbank"
    assert captured.err == ""
    assert list(tmp_path.glob("*.csv")) == [source]


def test_cli_detect_bank_and_bank_are_mutually_exclusive(tmp_path, capsys):
    source = tmp_path / "tbank.csv"
    _write_inline_tbank(source)
    with pytest.raises(SystemExit) as excinfo:
        main(["-i", str(source), "--detect-bank", "--bank", "tbank"])
    assert excinfo.value.code != 0
    captured = capsys.readouterr()
    assert "--detect-bank" in captured.err
    assert "--bank" in captured.err


def test_cli_output_omitted_generates_default_in_cwd(tmp_path, monkeypatch, capsys):
    source = tmp_path / "tbank.csv"
    _write_inline_tbank(source)
    monkeypatch.chdir(tmp_path)
    exit_code = main(["-i", str(source)])
    captured = capsys.readouterr()
    assert exit_code == 0
    generated = list(tmp_path.glob("tbank_*.csv"))
    assert len(generated) == 1
    assert DEFAULT_FILENAME_RE.fullmatch(generated[0].name)
    path_token = captured.out.strip().split(" -> ", 1)[1]
    assert Path(path_token).resolve() == generated[0].resolve()
    assert captured.out.strip().startswith("2 transactions -> ")
    assert captured.err == ""
    _assert_canonical_csv(generated[0], 2)


def test_cli_output_omitted_with_alias_uses_canonical_name(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "tbank.csv"
    _write_inline_tbank(source)
    monkeypatch.chdir(tmp_path)
    exit_code = main(["-i", str(source), "--bank", "т-банк"])
    captured = capsys.readouterr()
    assert exit_code == 0
    generated = list(tmp_path.glob("tbank_*.csv"))
    assert len(generated) == 1
    assert DEFAULT_FILENAME_RE.fullmatch(generated[0].name)
    assert captured.out.strip().startswith("2 transactions -> ")


def test_cli_output_flag_writes_exact_path_and_no_default(
    tmp_path, monkeypatch, capsys
):
    source = tmp_path / "tbank.csv"
    output = tmp_path / "requested.csv"
    _write_inline_tbank(source)
    monkeypatch.chdir(tmp_path)
    exit_code = main(["-i", str(source), "-o", str(output), "--bank", "tbank"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert output.exists()
    assert captured.out.strip() == f"2 transactions -> {output}"
    assert list(tmp_path.glob("tbank_*.csv")) == []
    assert sorted(p.name for p in tmp_path.glob("*.csv")) == [
        "requested.csv",
        "tbank.csv",
    ]


def test_cli_detect_bank_missing_input_exit_one(tmp_path, capsys):
    missing = tmp_path / "missing.csv"
    exit_code = main(["-i", str(missing), "--detect-bank"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("bank-parser: error:")
    assert "Traceback (most recent call last)" not in captured.err


def test_cli_detect_bank_unknown_format_exit_one(tmp_path, capsys):
    source = tmp_path / "input.txt"
    source.write_text("hello\n", encoding="utf-8")
    exit_code = main(["-i", str(source), "--detect-bank"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("bank-parser: error:")
    assert "unsupported input format" in captured.err
    assert "Traceback (most recent call last)" not in captured.err


def test_cli_detect_bank_undetectable_csv_exit_one(tmp_path, capsys):
    source = tmp_path / "unknown.csv"
    _write_unknown_csv(source)
    exit_code = main(["-i", str(source), "--detect-bank"])
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("bank-parser: error:")
    assert "Could not detect the bank" in captured.err
    assert "Traceback (most recent call last)" not in captured.err
