#!/usr/bin/env python3
"""Standalone QA comparison harness for the ``bank_parser`` canonical CSV output.

This is deliberately *not* a unit-test suite: it is a CLI tool that runs the
parser end-to-end, reads both the generated CSV and a handwritten reference CSV,
and compares them semantically.

Typical use::

    # Generate T-Bank output into tmp/ and compare with the handwritten reference
    python scripts/verify.py

    # Compare any generated/reference pair (no generation)
    python scripts/verify.py --compare-only \\
        --generated tmp/verify/Т-Банк.csv --reference data/output/Т-Банк.csv

Semantic rules
--------------
* Missing trailing empty fields are treated as equal (the handwritten reference
  is known to omit the trailing comma on its last row).
* Only outer whitespace is trimmed; inner characters (including NBSP) are
  compared exactly.
* ``date`` is compared as a calendar date (DD/MM/YYYY canonical form is
  checked separately for the generated file), ``amount`` as a ``Decimal``
  (2-decimal canonical formatting is checked separately), and every other
  field byte-for-byte after trimming.

Extra checks
------------
* Canonical format checks on the *generated* file: UTF-8 BOM, LF-only, exact
  header, 8 fields per row, empty 8th placeholder, 2-decimal amounts,
  DD/MM/YYYY dates, valid operation types, no trailing whitespace, no blank
  rows, final newline.
* An independent oracle derived from the input export (implemented here from
  ``docs/spec.md``, not from the package under test) is used to tell a real
  parser bug from a manual typo in the handwritten reference.  A difference
  between generated and reference output is only excused when the reference
  itself disagrees with the oracle at exactly that row/field.

Exit codes
----------
* ``0`` -- semantic match (and canonical format OK for the generated file)
* ``1`` -- semantic mismatch or canonical format violation
* ``2`` -- harness error (missing files, generation failure, unparsable CSV)
"""

from __future__ import annotations

import argparse
import codecs
import csv
import io
import os
import re
import subprocess
import sys
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

BOM = codecs.BOM_UTF8
HEADER = ["date", "merchant", "amount", "currency", "category", "type", "comment", ""]
FIELDS = ("date", "merchant", "amount", "currency", "category", "type", "comment")
TYPE_DEBIT = "Списание"
TYPE_CREDIT = "Пополнение"
TYPES = (TYPE_DEBIT, TYPE_CREDIT)

INPUT_DATE_FORMATS = ("%d.%m.%Y %H:%M:%S", "%d.%m.%Y", "%d/%m/%Y")
ANY_DATE_FORMATS = INPUT_DATE_FORMATS + ("%Y-%m-%d",)
OUTPUT_DATE_FORMAT = "%d/%m/%Y"
AMOUNT_RE = re.compile(r"^\d+\.\d{2}$")
DELIMITERS = (",", ";", "\t")

DEFAULT_INPUT = ROOT / "data" / "input" / "T-Банк.csv"
DEFAULT_REFERENCE = ROOT / "data" / "output" / "Т-Банк.csv"
DEFAULT_GENERATED = ROOT / "tmp" / "verify" / "Т-Банк.csv"

MINUS_LIKE = ("\u2212",)  # unicode minus
SPACE_LIKE = ("\xa0", "\u202f", "\u2009", "\u2007", " ")  # NBSP / thin spaces


class HarnessError(Exception):
    """Raised when the harness itself cannot perform the comparison."""


# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #


@dataclass
class Record:
    """One data row, already split into the 7 semantic fields."""

    values: dict[str, str]
    placeholder: str = ""
    extra_fields: list[str] = field(default_factory=list)
    raw_field_count: int = 8

    def pretty(self) -> str:
        parts = [f"{name}={self.values.get(name, '')!r}" for name in FIELDS]
        if self.placeholder:
            parts.append(f"placeholder={self.placeholder!r}")
        if self.extra_fields:
            parts.append(f"extra={self.extra_fields!r}")
        return "{" + ", ".join(parts) + "}"


@dataclass
class Diff:
    row: int
    kind: str  # field | placeholder | reference_extra_fields | generated_extra_fields
    #           | missing_row | extra_row
    field: str = ""
    reference: str | None = None
    generated: str | None = None

    def describe(self) -> str:
        if self.kind == "field":
            return (
                f"row {self.row}: {self.field}: "
                f"generated={self.generated!r} reference={self.reference!r}"
            )
        if self.kind == "placeholder":
            return (
                f"row {self.row}: 8th placeholder field: "
                f"generated={self.generated!r} reference={self.reference!r}"
            )
        if self.kind == "missing_row":
            return f"row {self.row}: missing in generated; reference has {self.reference}"
        if self.kind == "extra_row":
            return f"row {self.row}: extra in generated; generated has {self.generated}"
        if self.kind == "reference_extra_fields":
            return f"row {self.row}: reference has extra fields {self.reference!r}"
        if self.kind == "generated_extra_fields":
            return f"row {self.row}: generated has extra fields {self.generated!r}"
        return f"row {self.row}: {self.kind}"

    def key(self) -> tuple[int, str]:
        return (self.row, self.field)


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def strip_outer(text: str) -> str:
    """Trim only outer whitespace (innermost characters are preserved)."""
    return text.strip()


def format_amount(value: Decimal) -> str:
    """Format a Decimal as a canonical 2-decimal string."""
    return f"{value:.2f}"


def parse_amount(raw: str) -> Decimal | None:
    """Parse a bank amount: decimal comma/dot, unicode minus, NBSP thousands."""
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return None
    for ch in MINUS_LIKE:
        text = text.replace(ch, "-")
    for ch in SPACE_LIKE:
        text = text.replace(ch, "")
    # Drop currency symbols / letters, keep the numeric skeleton.
    text = "".join(ch for ch in text if ch.isdigit() or ch in ".,-+")
    if not any(ch.isdigit() for ch in text):
        return None
    text = text.replace(",", ".")
    try:
        return Decimal(text)
    except InvalidOperation:
        return None


def parse_date(raw: str, formats: tuple[str, ...]) -> date | None:
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def decode_bytes(data: bytes) -> tuple[str, str]:
    """Decode a bank export using the spec's whole-file fallback order."""
    if data.startswith(BOM):
        return data.decode("utf-8-sig"), "utf-8-sig"
    try:
        return data.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        return data.decode("cp1251"), "cp1251"


def sniff_delimiter(text: str) -> str:
    """Pick the delimiter that yields the most/consistent columns."""
    best: tuple[tuple[int, int], str] | None = None
    for delimiter in DELIMITERS:
        try:
            rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
        except csv.Error:
            continue
        non_empty = [row for row in rows if any(cell.strip() for cell in row)]
        if not non_empty:
            continue
        lengths = [len(row) for row in non_empty]
        mode_len = max(set(lengths), key=lambda n: (lengths.count(n), n))
        score = (mode_len, lengths.count(mode_len))
        if best is None or score > best[0]:
            best = (score, delimiter)
    return best[1] if best is not None else ","


def parse_csv_text(text: str) -> tuple[str, list[list[str]], int]:
    """Return (delimiter, non-empty rows including header, blank-row count)."""
    delimiter = sniff_delimiter(text)
    try:
        raw_rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error as exc:  # pragma: no cover - csv is lenient in practice
        raise HarnessError(f"cannot parse CSV: {exc}") from exc
    rows: list[list[str]] = []
    blank_rows = 0
    for row in raw_rows:
        if any(strip_outer(cell) for cell in row):
            rows.append(row)
        else:
            blank_rows += 1
    return delimiter, rows, blank_rows


def field_equal(name: str, reference_value: str, generated_value: str) -> bool:
    if reference_value == generated_value:
        return True
    if name == "amount":
        ref_amount = parse_amount(reference_value)
        gen_amount = parse_amount(generated_value)
        return (
            ref_amount is not None
            and gen_amount is not None
            and ref_amount == gen_amount
        )
    if name == "date":
        ref_date = parse_date(reference_value, ANY_DATE_FORMATS)
        gen_date = parse_date(generated_value, ANY_DATE_FORMATS)
        return ref_date is not None and gen_date is not None and ref_date == gen_date
    return False


def describe_odd_chars(value: str) -> str:
    """Human hint listing unusual invisible characters in a value."""
    names: list[str] = []
    for ch in value:
        if ch in "\xa0\u202f\u2009\u2007\u2212\t\r\n" or unicodedata.category(ch) == "Cf":
            name = unicodedata.name(ch, "UNKNOWN")
            if name not in names:
                names.append(name)
    return ", ".join(names)


# --------------------------------------------------------------------------- #
# File loading / stats
# --------------------------------------------------------------------------- #


def load_file(path: Path) -> tuple[bytes, str, str]:
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise HarnessError(f"cannot read {path}: {exc}") from exc
    text, encoding = decode_bytes(data)
    return data, text, encoding


def byte_stats(data: bytes) -> dict[str, object]:
    crlf = data.count(b"\r\n")
    total_lf = data.count(b"\n")
    total_cr = data.count(b"\r")
    bare_lf = total_lf - crlf
    bare_cr = total_cr - crlf

    split = data.split(b"\n")
    physical_lines = split[:-1] if split and split[-1] == b"" else split
    trailing_ws = sum(
        1 for line in physical_lines if line.rstrip(b" \t") != line
    )
    return {
        "size": len(data),
        "bom": data.startswith(BOM),
        "double_bom": data.startswith(BOM + BOM),
        "crlf": crlf,
        "bare_lf": bare_lf,
        "bare_cr": bare_cr,
        "ends_with_newline": data.endswith(b"\n"),
        "ends_with_blank_line": data.endswith(b"\n\n"),
        "line_count": len(physical_lines),
        "trailing_ws_lines": trailing_ws,
        "nul_bytes": data.count(b"\x00"),
    }


def records_from_rows(rows: list[list[str]]) -> list[Record]:
    records: list[Record] = []
    for raw_row in rows:
        padded = (raw_row + [""] * 7)[:7]
        values = {name: strip_outer(padded[index]) for index, name in enumerate(FIELDS)}
        placeholder = (
            strip_outer(raw_row[7]) if len(raw_row) > 7 else ""
        )
        extra_fields = (
            [strip_outer(cell) for cell in raw_row[8:]] if len(raw_row) > 8 else []
        )
        records.append(
            Record(
                values=values,
                placeholder=placeholder,
                extra_fields=extra_fields,
                raw_field_count=len(raw_row),
            )
        )
    return records


def print_byte_stats(label: str, path: Path, data: bytes, encoding: str,
                     delimiter: str, rows: list[list[str]], blank_rows: int) -> None:
    stats = byte_stats(data)
    data_rows = rows[1:] if rows else []
    lengths: dict[int, int] = {}
    for row in data_rows:
        lengths[len(row)] = lengths.get(len(row), 0) + 1
    print(f"  {label}: {path}")
    print(f"    size: {stats['size']:,} bytes")
    print(f"    decoded as: {encoding}")
    print(f"    BOM: {'yes' if stats['bom'] else 'no'}"
          f"{' (DOUBLE BOM!)' if stats['double_bom'] else ''}")
    print(
        "    line endings: "
        f"LF={stats['bare_lf']}, CRLF={stats['crlf']}, CR={stats['bare_cr']}"
    )
    print(
        f"    final newline: {'yes' if stats['ends_with_newline'] else 'no'}"
        f"{' (trailing blank line!)' if stats['ends_with_blank_line'] else ''}"
    )
    print(f"    physical lines: {stats['line_count']:,}")
    print(f"    delimiter: {delimiter!r}")
    print(f"    header: {[strip_outer(c) for c in rows[0]] if rows else []!r}")
    print(f"    data rows: {len(data_rows)} (blank rows skipped: {blank_rows})")
    print(f"    field-count distribution: {dict(sorted(lengths.items()))}")
    print(f"    lines with trailing whitespace: {stats['trailing_ws_lines']}")
    if stats["nul_bytes"]:
        print(f"    NUL bytes: {stats['nul_bytes']}")


# --------------------------------------------------------------------------- #
# Oracle from input export (independent implementation of docs/spec.md)
# --------------------------------------------------------------------------- #


def derive_expected(input_path: Path) -> tuple[list[Record], dict[str, object]]:
    data, text, encoding = load_file(input_path)
    delimiter, rows, blank_rows = parse_csv_text(text)
    if not rows:
        raise HarnessError(f"{input_path}: no CSV rows found")

    header = [strip_outer(cell) for cell in rows[0]]
    columns: dict[str, int] = {}
    for index, name in enumerate(header):
        columns.setdefault(name, index)

    required = ("Дата операции", "Сумма операции", "Описание")
    missing = [name for name in required if name not in columns]
    if missing:
        raise HarnessError(
            f"{input_path}: missing required header(s): {', '.join(missing)}"
        )

    def get(row: list[str], name: str) -> str:
        index = columns.get(name)
        if index is None or index >= len(row):
            return ""
        return row[index]

    expected: list[Record] = []
    for row_number, row in enumerate(rows[1:], start=1):
        raw_date = get(row, "Дата операции")
        parsed_date = parse_date(raw_date, INPUT_DATE_FORMATS)
        if parsed_date is None:
            raise HarnessError(
                f"{input_path}: data row {row_number}: cannot parse date {raw_date!r}"
            )
        raw_amount = get(row, "Сумма операции")
        signed_amount = parse_amount(raw_amount)
        if signed_amount is None:
            raise HarnessError(
                f"{input_path}: data row {row_number}: cannot parse amount "
                f"{raw_amount!r}"
            )
        currency = strip_outer(get(row, "Валюта операции")) or strip_outer(
            get(row, "Валюта счёта")
        )
        category = strip_outer(get(row, "Категория по-умолчанию")) or strip_outer(
            get(row, "Ваша категория")
        )
        values = {
            "date": parsed_date.strftime(OUTPUT_DATE_FORMAT),
            "merchant": get(row, "Описание"),
            "amount": format_amount(abs(signed_amount)),
            "currency": currency,
            "category": category,
            "type": TYPE_DEBIT if signed_amount <= 0 else TYPE_CREDIT,
            "comment": get(row, "Сообщение"),
        }
        expected.append(Record(values=values))
    meta = {
        "encoding": encoding,
        "delimiter": delimiter,
        "blank_rows": blank_rows,
        "data_rows": len(expected),
    }
    return expected, meta


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #


def compare_records(
    reference: list[Record],
    generated: list[Record],
) -> list[Diff]:
    """Compare generated records against reference records, field by field."""
    diffs: list[Diff] = []
    total = max(len(reference), len(generated))
    for index in range(total):
        row_number = index + 1
        if index >= len(reference):
            diffs.append(Diff(row_number, "extra_row", generated=generated[index].pretty()))
            continue
        if index >= len(generated):
            diffs.append(
                Diff(row_number, "missing_row", reference=reference[index].pretty())
            )
            continue

        ref_record = reference[index]
        gen_record = generated[index]

        for name in FIELDS:
            ref_value = ref_record.values.get(name, "")
            gen_value = gen_record.values.get(name, "")
            if not field_equal(name, ref_value, gen_value):
                diffs.append(
                    Diff(
                        row=row_number,
                        kind="field",
                        field=name,
                        reference=ref_value,
                        generated=gen_value,
                    )
                )

        if ref_record.placeholder or gen_record.placeholder:
            if ref_record.placeholder != gen_record.placeholder:
                diffs.append(
                    Diff(
                        row=row_number,
                        kind="placeholder",
                        reference=ref_record.placeholder,
                        generated=gen_record.placeholder,
                    )
                )

        if ref_record.extra_fields:
            diffs.append(
                Diff(
                    row=row_number,
                    kind="reference_extra_fields",
                    reference=ref_record.extra_fields,
                )
            )
        if gen_record.extra_fields:
            diffs.append(
                Diff(
                    row=row_number,
                    kind="generated_extra_fields",
                    generated=gen_record.extra_fields,
                )
            )
    return diffs


def print_diffs(title: str, diffs: list[Diff], limit: int) -> None:
    print(f"  {title}: {len(diffs)} difference(s)")
    for diff in diffs[:limit]:
        print(f"    {diff.describe()}")
        for hint_field in (diff.reference, diff.generated):
            if isinstance(hint_field, str):
                hint = describe_odd_chars(hint_field)
                if hint:
                    print(f"      (unusual chars: {hint})")
    if len(diffs) > limit:
        print(f"    ... {len(diffs) - limit} more difference(s) suppressed")


# --------------------------------------------------------------------------- #
# Canonical format checks for the generated file
# --------------------------------------------------------------------------- #


def canonical_checks(
    generated_path: Path,
    data: bytes,
    text: str,
    encoding: str,
    delimiter: str,
    rows: list[list[str]],
    blank_rows: int,
    expect_rows: int | None,
) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        checks.append((name, ok, detail))

    data_rows = rows[1:] if rows else []
    header = [strip_outer(cell) for cell in rows[0]] if rows else []

    check("UTF-8 BOM present", data.startswith(BOM) and not data.startswith(BOM + BOM))
    check("encoding decodes as UTF-8", encoding in ("utf-8", "utf-8-sig"),
          f"decoded as {encoding}")
    check("LF line endings only", b"\r" not in data)
    check("single final newline", data.endswith(b"\n") and not data.endswith(b"\n\n"))
    check("no NUL bytes", b"\x00" not in data)
    check("delimiter is ','", delimiter == ",")
    check("exact 8-field header", header == HEADER, f"header={header!r}")
    check("no blank rows", blank_rows == 0, f"{blank_rows} blank row(s)")
    check("no trailing whitespace", byte_stats(data)["trailing_ws_lines"] == 0)

    bad_lengths = [i for i, row in enumerate(data_rows, 1) if len(row) != 8]
    check(
        "8 fields in every data row",
        not bad_lengths,
        f"rows with bad field counts: {bad_lengths[:20]}",
    )

    bad_placeholder = [
        i for i, row in enumerate(data_rows, 1) if len(row) > 7 and row[7] != ""
    ]
    check(
        "8th placeholder field always empty",
        not bad_placeholder,
        f"rows with non-empty placeholder: {bad_placeholder[:20]}",
    )

    bad_amounts = [
        (i, row[2]) for i, row in enumerate(data_rows, 1)
        if len(row) < 3 or not AMOUNT_RE.match(row[2])
    ]
    check(
        "amounts are absolute with exactly 2 decimals",
        not bad_amounts,
        f"bad amounts: {bad_amounts[:20]}",
    )

    bad_dates = [
        (i, row[0]) for i, row in enumerate(data_rows, 1)
        if len(row) < 1 or parse_date(row[0], (OUTPUT_DATE_FORMAT,)) is None
    ]
    check(
        "dates are DD/MM/YYYY",
        not bad_dates,
        f"bad dates: {bad_dates[:20]}",
    )

    bad_types = [
        (i, row[5]) for i, row in enumerate(data_rows, 1)
        if len(row) < 6 or row[5] not in TYPES
    ]
    check(
        "types are Списание/Пополнение",
        not bad_types,
        f"bad types: {bad_types[:20]}",
    )

    if expect_rows is not None:
        check(
            f"exactly {expect_rows} data rows",
            len(data_rows) == expect_rows,
            f"{len(data_rows)} data rows",
        )

    return checks


# --------------------------------------------------------------------------- #
# Reference audit
# --------------------------------------------------------------------------- #


def reference_audit(
    rows: list[list[str]], blank_rows: int, stats: dict[str, object]
) -> list[str]:
    notes: list[str] = []
    data_rows = rows[1:] if rows else []
    if blank_rows:
        notes.append(f"{blank_rows} blank row(s) present (ignored by comparison)")
    bad_lengths = [(i, len(row)) for i, row in enumerate(data_rows, 1) if len(row) != 8]
    if bad_lengths:
        shown = ", ".join(f"row {i}: {n} fields" for i, n in bad_lengths[:20])
        extra = "" if len(bad_lengths) <= 20 else f" (+{len(bad_lengths) - 20} more)"
        notes.append(f"field-count anomalies: {shown}{extra}")
    trailing = stats["trailing_ws_lines"]
    if trailing:
        notes.append(f"{trailing} line(s) with trailing whitespace")

    seen: dict[tuple[str, ...], int] = {}
    duplicates: list[int] = []
    for index, row in enumerate(data_rows, 1):
        key = tuple(strip_outer(cell) for cell in row[:7])
        if key in seen:
            duplicates.append(index)
        else:
            seen[key] = index
    if duplicates:
        notes.append(f"duplicate data rows at: {duplicates[:20]}")
    return notes


# --------------------------------------------------------------------------- #
# Tool execution
# --------------------------------------------------------------------------- #


def run_tool(
    root: Path, input_path: Path, output_path: Path, bank: str | None
) -> str:
    if not input_path.is_file():
        raise HarnessError(f"input file not found: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        output_path.unlink()
    except FileNotFoundError:
        pass

    env = dict(os.environ)
    src = str(root / "src")
    env["PYTHONPATH"] = src + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONIOENCODING"] = "utf-8"

    command = [
        sys.executable,
        "-m",
        "bank_parser",
        "--input",
        str(input_path),
        "--output",
        str(output_path),
    ]
    if bank:
        command += ["--bank", bank]

    print("  command:")
    print(f"    PYTHONPATH={src} {' '.join(command)}")
    try:
        proc = subprocess.run(
            command,
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
    except OSError as exc:
        raise HarnessError(f"cannot launch parser: {exc}") from exc

    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    print(f"  exit code: {proc.returncode}")
    print(f"  stdout: {stdout!r}")
    print(f"  stderr: {stderr!r}")
    if proc.returncode != 0:
        raise HarnessError(
            f"parser CLI failed with exit code {proc.returncode}: {stderr or stdout}"
        )
    if not output_path.is_file():
        raise HarnessError(f"parser reported success but did not write {output_path}")
    return stdout


# --------------------------------------------------------------------------- #
# Argument parsing / main
# --------------------------------------------------------------------------- #


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compare bank_parser canonical CSV output with a reference CSV "
        "(semantic CSV comparison + byte-level stats).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python scripts/verify.py\n"
            "  python scripts/verify.py --compare-only \\\n"
            "      --generated tmp/verify/Т-Банк.csv \\\n"
            "      --reference data/output/Т-Банк.csv\n"
        ),
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help=f"repository root (default: {ROOT})",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=None,
        help=(
            "input export used for generation and for the independent oracle audit "
            f"(default in generate mode: {DEFAULT_INPUT})"
        ),
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=DEFAULT_REFERENCE,
        help=f"handwritten reference CSV (default: {DEFAULT_REFERENCE})",
    )
    parser.add_argument(
        "--generated",
        type=Path,
        default=DEFAULT_GENERATED,
        help=f"generated CSV, overwritten in generate mode (default: {DEFAULT_GENERATED})",
    )
    parser.add_argument(
        "--compare-only",
        action="store_true",
        help="do not run the parser; compare an existing --generated file",
    )
    parser.add_argument(
        "--bank",
        default="tbank",
        help="bank alias passed to the CLI (default: tbank; empty string omits --bank)",
    )
    parser.add_argument(
        "--expect-rows",
        type=int,
        default=None,
        help="if set, require exactly N generated data rows",
    )
    parser.add_argument(
        "--no-canonical",
        action="store_true",
        help="skip canonical-format checks on the generated file",
    )
    parser.add_argument(
        "--no-oracle",
        action="store_true",
        help="skip the independent input-derived oracle audit",
    )
    parser.add_argument(
        "--max-diffs",
        type=int,
        default=200,
        help="maximum number of diffs printed per section (default: 200)",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    root: Path = args.root.resolve()
    reference_path: Path = args.reference
    generated_path: Path = args.generated
    input_path: Path | None = args.input

    print("=" * 78)
    print("bank_parser QA verification")
    print("=" * 78)
    print(f"root:        {root}")
    print(f"generated:   {generated_path}")
    print(f"reference:   {reference_path}")
    print(f"mode:        {'compare-only' if args.compare_only else 'generate + compare'}")
    print()

    # ---- 1. generation -------------------------------------------------- #
    print("[1/6] End-to-end parser run")
    if args.compare_only:
        if not generated_path.is_file():
            raise HarnessError(f"--compare-only but generated file not found: {generated_path}")
        print(f"  skipped generation; using existing {generated_path}")
        if input_path is None:
            print("  (no --input given; oracle audit disabled)")
    else:
        if input_path is None:
            input_path = DEFAULT_INPUT
        print(f"  input: {input_path}")
        run_tool(root, input_path, generated_path, args.bank or None)
    print()

    # ---- 2. load + byte stats ------------------------------------------ #
    if not reference_path.is_file():
        raise HarnessError(f"reference file not found: {reference_path}")
    if not generated_path.is_file():
        raise HarnessError(f"generated file not found: {generated_path}")

    gen_data, gen_text, gen_encoding = load_file(generated_path)
    ref_data, ref_text, ref_encoding = load_file(reference_path)
    gen_delimiter, gen_rows, gen_blank = parse_csv_text(gen_text)
    ref_delimiter, ref_rows, ref_blank = parse_csv_text(ref_text)

    if not gen_rows:
        raise HarnessError(f"generated file has no rows: {generated_path}")
    if not ref_rows:
        raise HarnessError(f"reference file has no rows: {reference_path}")

    ref_header = [strip_outer(cell) for cell in ref_rows[0]]
    if ref_header[:7] != HEADER[:7]:
        raise HarnessError(
            "reference header does not match the canonical field names; "
            f"got {ref_header!r}"
        )

    print("[2/6] Byte-level stats")
    print_byte_stats(
        "generated", generated_path, gen_data, gen_encoding,
        gen_delimiter, gen_rows, gen_blank,
    )
    print_byte_stats(
        "reference", reference_path, ref_data, ref_encoding,
        ref_delimiter, ref_rows, ref_blank,
    )
    print()

    # ---- 3. semantic comparison ---------------------------------------- #
    print("[3/6] Semantic comparison (generated vs reference)")
    ref_records = records_from_rows(ref_rows[1:])
    gen_records = records_from_rows(gen_rows[1:])
    print(
        f"  rows: generated={len(gen_records)} reference={len(ref_records)} "
        f"compared={max(len(gen_records), len(ref_records))}"
    )
    gen_ref_diffs = compare_records(ref_records, gen_records)
    if gen_ref_diffs:
        print_diffs("differences", gen_ref_diffs, args.max_diffs)
    else:
        print("  differences: none -- every field matches")
    print()

    # ---- 4. oracle audit ----------------------------------------------- #
    oracle_records: list[Record] | None = None
    gen_oracle_diffs: list[Diff] = []
    ref_oracle_diffs: list[Diff] = []
    oracle_meta: dict[str, object] | None = None
    oracle_enabled = input_path is not None and not args.no_oracle

    print("[4/6] Independent oracle audit (input-derived expectation)")
    if not oracle_enabled:
        print("  skipped (no input file / --no-oracle)")
    else:
        oracle_records, oracle_meta = derive_expected(input_path)
        print(
            f"  input: {input_path} (decoded {oracle_meta['encoding']}, "
            f"delimiter {oracle_meta['delimiter']!r})"
        )
        print(f"  oracle rows: {len(oracle_records)}")
        ref_oracle_diffs = compare_records(oracle_records, ref_records)
        gen_oracle_diffs = compare_records(oracle_records, gen_records)
        if ref_oracle_diffs:
            print_diffs("reference vs oracle (manual reference errors)", ref_oracle_diffs,
                        args.max_diffs)
        else:
            print("  reference vs oracle: 0 differences (no manual data errors detected)")
        if gen_oracle_diffs:
            print_diffs("generated vs oracle (parser bugs)", gen_oracle_diffs,
                        args.max_diffs)
        else:
            print("  generated vs oracle: 0 differences")
    print()

    # ---- 5. canonical checks ------------------------------------------- #
    print("[5/6] Canonical format checks (generated)")
    canonical_results: list[tuple[str, bool, str]] = []
    if args.no_canonical:
        print("  skipped (--no-canonical)")
    else:
        canonical_results = canonical_checks(
            generated_path, gen_data, gen_text, gen_encoding, gen_delimiter,
            gen_rows, gen_blank, args.expect_rows,
        )
        for name, ok, detail in canonical_results:
            status = "PASS" if ok else "FAIL"
            line = f"  [{status}] {name}"
            if not ok and detail:
                line += f" -- {detail}"
            print(line)
    print()

    # ---- 6. interpretation / verdict ----------------------------------- #
    print("[6/6] Verdict")
    ref_typo_keys = {diff.key() for diff in ref_oracle_diffs}
    unexplained: list[Diff] = []
    explained: list[Diff] = []
    for diff in gen_ref_diffs:
        if diff.kind == "field" and diff.key() in ref_typo_keys:
            explained.append(diff)
        else:
            unexplained.append(diff)

    canonical_failures = [name for name, ok, _ in canonical_results if not ok]
    oracle_failures = len(gen_oracle_diffs)

    if explained:
        print(
            f"  {len(explained)} generated-vs-reference difference(s) are explained by "
            "manual reference errors (reference disagrees with the input oracle there):"
        )
        for diff in explained[: args.max_diffs]:
            print(f"    {diff.describe()}")

    semantic_fail = bool(unexplained)
    if semantic_fail:
        print(
            f"  {len(unexplained)} UNEXPLAINED semantic difference(s):"
        )
        for diff in unexplained[: args.max_diffs]:
            print(f"    {diff.describe()}")

    ok = not semantic_fail and not canonical_failures and oracle_failures == 0
    if ok:
        print()
        print(
            f"VERDICT: PASS -- {len(gen_records)} generated rows semantically match "
            f"{len(ref_records)} reference rows"
            + (
                f"; {len(explained)} manual-reference difference(s) explained by the oracle"
                if explained else ""
            )
            + ("; canonical format OK" if not args.no_canonical else "")
        )
        print()
        return 0

    print()
    reasons: list[str] = []
    if semantic_fail:
        reasons.append(f"{len(unexplained)} unexplained generated-vs-reference difference(s)")
    if oracle_failures:
        reasons.append(f"{oracle_failures} generated-vs-oracle difference(s)")
    if canonical_failures:
        reasons.append(f"canonical check failure(s): {', '.join(canonical_failures)}")
    print(f"VERDICT: FAIL -- {'; '.join(reasons)}")
    print()
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return run(args)
    except HarnessError as exc:
        print(f"\nverify: error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:  # pragma: no cover
        print("\nverify: interrupted", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
