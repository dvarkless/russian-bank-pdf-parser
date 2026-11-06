"""Tests for the CSV readers (pandas-backed and stdlib fallback)."""

from __future__ import annotations

import codecs
import csv
import io
from pathlib import Path

import pytest

from bank_parser.adapters.csv_source import PandasTableReader, StdlibCsvReader
from bank_parser.readers import read_table


def _write_csv(
    path: Path,
    rows: list[list[str]],
    *,
    delimiter: str = ";",
    encoding: str = "utf-8",
    bom: bool = False,
    line_terminator: str = "\n",
) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.writer(
        buffer, delimiter=delimiter, lineterminator=line_terminator
    )
    writer.writerows(rows)
    data = buffer.getvalue().encode(encoding)
    if bom:
        data = codecs.BOM_UTF8 + data
    path.write_bytes(data)


def _cells(table) -> list[list[str]]:
    return [list(row.cells) for row in table.rows]


@pytest.mark.parametrize("delimiter", [";", ",", "\t"])
def test_readers_support_semicolon_comma_tab(tmp_path, delimiter):
    path = tmp_path / "data.csv"
    rows = [["name", "value"], ["alpha", "1"], ["beta", "2"]]
    _write_csv(path, rows, delimiter=delimiter)
    expected = rows
    assert _cells(PandasTableReader().read(path)) == expected
    assert _cells(StdlibCsvReader().read(path)) == expected
    assert read_table(path) == expected


def test_readers_handle_bom_and_crlf(tmp_path):
    path = tmp_path / "bom_crlf.csv"
    rows = [["a", "b"], ["1", "2"]]
    _write_csv(path, rows, bom=True, line_terminator="\r\n")
    assert _cells(PandasTableReader().read(path)) == rows
    assert _cells(StdlibCsvReader().read(path)) == rows
    assert read_table(path) == rows


def test_readers_handle_cp1251(tmp_path):
    path = tmp_path / "cp1251.csv"
    rows = [["Дата", "Описание"], ["01.05.2026", "Пятёрочка"]]
    _write_csv(path, rows, encoding="cp1251")
    assert _cells(PandasTableReader().read(path)) == rows
    assert _cells(StdlibCsvReader().read(path)) == rows
    assert read_table(path) == rows


def test_readers_skip_blank_rows(tmp_path):
    path = tmp_path / "blanks.csv"
    path.write_text(
        "a;b\n\n1;2\n;\n\n3;4\n", encoding="utf-8", newline=""
    )
    expected = [["a", "b"], ["1", "2"], ["3", "4"]]
    assert _cells(PandasTableReader().read(path)) == expected
    assert _cells(StdlibCsvReader().read(path)) == expected
    assert read_table(path) == expected


def test_readers_preserve_quoted_delimiter_and_newline(tmp_path):
    path = tmp_path / "quoted.csv"
    rows = [
        ["id", "text"],
        ["1", "a;b"],
        ["2", "line one\nline two"],
        ["3", 'he said "hi"'],
    ]
    _write_csv(path, rows, delimiter=";")
    assert _cells(PandasTableReader().read(path)) == rows
    assert _cells(StdlibCsvReader().read(path)) == rows
    assert read_table(path) == rows


def test_readers_preserve_reordered_headers(tmp_path):
    path = tmp_path / "reordered.csv"
    rows = [["c", "a", "b"], ["3", "1", "2"]]
    _write_csv(path, rows)
    assert _cells(PandasTableReader().read(path)) == rows
    assert _cells(StdlibCsvReader().read(path)) == rows


def test_read_header_returns_cleaned_header(tmp_path):
    path = tmp_path / "header.csv"
    path.write_bytes(
        codecs.BOM_UTF8 + "  date ; merchant \r\n1;2\r\n".encode("utf-8")
    )
    expected = ("date", "merchant")
    assert PandasTableReader().read_header(path) == expected
    assert StdlibCsvReader().read_header(path) == expected


def test_stdlib_reader_keeps_physical_row_numbers_for_blank_lines(tmp_path):
    path = tmp_path / "physical.csv"
    path.write_text("a;b\n\n1;2\n", encoding="utf-8", newline="")
    table = StdlibCsvReader().read(path)
    assert [(row.cells, row.physical_row) for row in table.rows] == [
        (("a", "b"), 1),
        (("1", "2"), 3),
    ]


def test_legacy_read_table_matches_stdlib_reader(tmp_path):
    path = tmp_path / "legacy.csv"
    rows = [["a", "b"], ["1", "2"]]
    _write_csv(path, rows, delimiter=",")
    assert read_table(path) == _cells(StdlibCsvReader().read(path))
