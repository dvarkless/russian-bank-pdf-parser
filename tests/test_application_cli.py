"""End-to-end tests for Application, PipelineResult, CLI and legacy get_parser."""

from __future__ import annotations

import codecs
from pathlib import Path

import pytest

from bank_parser.banks import get_parser
from bank_parser.cli import build_application, main
from bank_parser.pipeline import PipelineResult


def _write_inline_tbank(path: Path) -> None:
    path.write_text(
        "Дата операции;Сумма операции;Описание\n"
        "01.05.2026 10:00:00;-100,00;Shop\n"
        "02.05.2026;+250,50;Employer\n",
        encoding="utf-8",
        newline="",
    )


def _write_inline_sber17(path: Path) -> None:
    path.write_text(
        "Дата операции;Сумма операции;Описание\n"
        "01.05.2026 10:00:00;-100,00;Shop\n",
        encoding="utf-8",
        newline="",
    )


def test_application_convert_returns_pipeline_result(tmp_path):
    source = tmp_path / "in.csv"
    output = tmp_path / "out.csv"
    _write_inline_tbank(source)
    app = build_application()
    result = app.convert(source, output, bank="tbank")
    assert isinstance(result, PipelineResult)
    assert result.transactions_written == 2
    assert result.bank == "tbank"
    assert result.input_path == source
    assert result.output_path == output
    assert output.read_bytes().startswith(codecs.BOM_UTF8)
    rows = output.read_text(encoding="utf-8-sig").splitlines()
    assert len(rows) == 3
    assert rows[0] == "date,merchant,amount,currency,category,type,comment,"
    assert rows[1].split(",")[:3] == ["01/05/2026", "Shop", "100.00"]
    assert rows[2].split(",")[5] == "Пополнение"


def test_application_read_transactions_does_not_write_output(tmp_path):
    source = tmp_path / "in.csv"
    _write_inline_tbank(source)
    app = build_application()
    txs = app.read_transactions(source, bank="tbank")
    assert len(txs) == 2
    assert [tx.merchant for tx in txs] == ["Shop", "Employer"]
    assert not (tmp_path / "out.csv").exists()


def test_cli_main_success_line_and_exit_zero(tmp_path, capsys):
    source = tmp_path / "in.csv"
    output = tmp_path / "out.csv"
    _write_inline_tbank(source)
    exit_code = main(["-i", str(source), "-o", str(output), "--bank", "tbank"])
    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.strip() == f"2 transactions -> {output}"
    assert captured.err == ""
    assert output.exists()


def test_cli_main_missing_input_exit_one_without_traceback(tmp_path, capsys):
    missing = tmp_path / "missing.csv"
    output = tmp_path / "out.csv"
    exit_code = main(
        ["-i", str(missing), "-o", str(output), "--bank", "tbank"]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert captured.err.startswith("bank-parser: error:")
    assert "Traceback (most recent call last)" not in captured.err
    assert not output.exists()


def test_cli_version_exits_zero_and_prints_version(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert "bank-parser 1.0.0" in captured.out


def test_cli_unknown_bank_exit_one_without_traceback(tmp_path, capsys):
    source = tmp_path / "in.csv"
    _write_inline_tbank(source)
    exit_code = main(
        ["-i", str(source), "-o", str(tmp_path / "out.csv"), "--bank", "nope"]
    )
    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Unsupported bank" in captured.err
    assert "Traceback (most recent call last)" not in captured.err


def test_legacy_get_parser_sber_resolves_csv_by_path(tmp_path):
    source = tmp_path / "sber.csv"
    _write_inline_sber17(source)
    txs = get_parser("sber")(source)
    assert len(txs) == 1
    assert txs[0].merchant == "Shop"


def test_legacy_get_parser_unknown_name_raises():
    with pytest.raises(Exception, match="Unsupported bank"):
        get_parser("nope")


@pytest.mark.skipif(
    not all(
        (Path("data/input") / name).exists()
        for name in ("T-Банк.csv", "Сбер_csv.csv", "Альфа.CSV", "Сбер.pdf", "Ozon.pdf")
    ),
    reason="real data/input fixtures are not present",
)
def test_all_five_real_fixtures_via_application():
    app = build_application()
    expected = {
        "data/input/T-Банк.csv": 117,
        "data/input/Сбер_csv.csv": 16,
        "data/input/Альфа.CSV": 96,
        "data/input/Сбер.pdf": 50,
        "data/input/Ozon.pdf": 47,
    }
    for path, count in expected.items():
        txs = app.read_transactions(Path(path))
        assert len(txs) == count
