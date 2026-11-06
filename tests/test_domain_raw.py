"""Tests for ColumnLayout, RawTable/RawRecord and related containers."""

from __future__ import annotations

from pathlib import Path

import pytest

from bank_parser.domain.models import InputFormat, SourceLocation
from bank_parser.domain.raw import (
    ColumnLayout,
    RawLine,
    RawRecord,
    RawRow,
    RawTable,
    RawText,
)
from bank_parser.errors import MissingHeaderError
from helpers import make_raw_text, make_raw_table


def test_column_layout_cleans_bom_and_leading_trailing_spaces():
    layout = ColumnLayout.from_header(["  date ", "\ufeffmerchant", "amount"])
    assert layout.headers == ("date", "merchant", "amount")
    assert layout.index_of("merchant") == 1
    assert layout.index_of("missing") is None


def test_column_layout_duplicate_first_occurrence_wins():
    layout = ColumnLayout.from_header(["a", "b", "a"])
    assert layout.index_of("a") == 0
    assert layout.headers == ("a", "b", "a")


def test_column_layout_require_raises_missing_header_with_location():
    layout = ColumnLayout.from_header(["date", "merchant"])
    location = SourceLocation(Path("x.csv"), InputFormat.CSV)
    with pytest.raises(MissingHeaderError) as excinfo:
        layout.require(("date", "amount"), location=location)
    assert "'amount'" in str(excinfo.value)
    assert "x.csv" in str(excinfo.value)


def test_raw_record_get_and_cell_bounds():
    layout = ColumnLayout.from_header(["a", "b"])
    record = RawRecord(
        cells=("one", "two"),
        layout=layout,
        location=SourceLocation(Path("x"), InputFormat.CSV),
    )
    assert record.get("a") == "one"
    assert record.get("b") == "two"
    assert record.get("missing") == ""
    assert record.cell(1) == "two"
    assert record.cell(99) == ""
    assert record.cell(-1) == ""


def test_raw_table_blank_row_filtering_and_physical_rows():
    table = make_raw_table(
        [["h1", "h2"], ["", ""], ["a", "b"], ["  ", ""], ["c", "d"]]
    )
    assert len(table.rows) == 5
    assert table.is_empty() is False
    assert [row.cells for row in table.non_empty_rows()] == [
        ("h1", "h2"), ("a", "b"), ("c", "d")
    ]
    assert [row.physical_row for row in table.rows] == [1, 2, 3, 4, 5]


def test_raw_table_empty_detection():
    table = make_raw_table([["", ""], ["  ", ""]])
    assert table.is_empty() is True
    assert table.non_empty_rows() == ()


def test_raw_row_cells_are_immutable_tuple():
    row = RawRow(cells=["a", "b"], physical_row=3)  # type: ignore[arg-type]
    assert row.cells == ("a", "b")
    with pytest.raises((AttributeError, TypeError)):
        row.cells = ("x",)  # type: ignore[misc]


def test_raw_text_preserves_page_and_line_and_detects_blank():
    raw = make_raw_text([(1, "first"), (2, "second"), (3, "   ")])
    assert [line.page for line in raw.lines] == [1, 2, 3]
    assert [line.line for line in raw.lines] == [1, 2, 3]
    assert raw.is_empty() is False
    blank = RawText(lines=(), source=raw.source)
    assert blank.is_empty() is True


def test_raw_line_rejects_nonpositive_numbers():
    with pytest.raises(ValueError):
        RawLine(text="x", page=0, line=1)
    with pytest.raises(ValueError):
        RawLine(text="x", page=1, line=0)
