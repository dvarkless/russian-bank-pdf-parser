# bank-parser

Convert Russian bank export files into a single, clean canonical transaction CSV.

`bank-parser` is a small Python CLI with a deliberately narrow dependency set.
It reads a bank's export file, maps it through a per-bank adapter into a common
`Transaction` model, and writes one canonical CSV that is easy to load into a
spreadsheet, database, or accounting tool.

The tool is deliberately boring: no network access, no binary floats for money
(`decimal.Decimal` only), and no hidden state. `pandas` is confined to tabular
transport, while PDF statements are read with `pdfplumber` (and `pypdf` as a
fallback). The output is byte-for-byte deterministic for a given input.

> Status: the **T-Bank** CSV adapter is the only bank implemented so far. The
> adapter registry is designed to be extended (other CSV banks and PDF
> statements); any other bank is unsupported today and will be rejected with a
> clear error.

---

## Features

- Header-name based column resolution (column order in the export does not
  matter; extra columns are ignored).
- Encoding tolerance: tries `utf-8-sig`, `utf-8`, then `cp1251`.
- Delimiter tolerance: `;`, `,` and tab, auto-detected from the header.
- Standard CSV quoting, including quoted cells that contain the delimiter or
  embedded newlines; CRLF and LF line endings both work.
- Amount tolerance: decimal comma or dot, Unicode minus, NBSP/thin-space
  thousands separators, optional currency symbols.
- Bank auto-detection from the filename or header, with an explicit `--bank`
  override.
- Clear error messages that name the offending data row.

---

## Supported banks

| Bank   | Input                     | Status                    |
|--------|---------------------------|---------------------------|
| T-Bank | T-Bank CSV export         | Supported (only bank)     |

Supported aliases for the `--bank` option: `tbank`, `t-bank`, `т-банк`,
`т банк` (case-insensitive).

Bank support lives behind a registry, so adding a new bank does not change the
CLI or the canonical writer. See
[Adding a bank adapter](#adding-a-bank-adapter).

---

## Canonical output format

Every output file is written in exactly this format:

| Property        | Value                                                              |
|-----------------|--------------------------------------------------------------------|
| Encoding        | UTF-8 **with BOM** (`utf-8-sig`)                                   |
| Line endings    | `\n` (LF), no trailing whitespace, single final newline            |
| Delimiter       | `,`                                                                |
| Columns         | 8 fields, header row first                                         |

Header row (note the trailing comma: the 8th field is an always-empty
placeholder that matches the established template):

```text
date,merchant,amount,currency,category,type,comment,
```

| Column     | Source / rule |
|------------|---------------|
| `date`     | Operation date, `DD/MM/YYYY` |
| `merchant` | Input `Описание` (T-Bank) |
| `amount`   | **Absolute** value, exactly 2 decimal digits, `.` separator (`-900,00` → `900.00`) |
| `currency` | Input `Валюта операции`; falls back to `Валюта счёта` when blank |
| `category` | Input `Категория по-умолчанию`; falls back to `Ваша категория` when blank |
| `type`     | `Списание` for a negative or zero signed amount, `Пополнение` for a positive one |
| `comment`  | Input `Сообщение` (may be empty) |
| (8th)      | Always empty (trailing comma) |

One data row is written per input transaction, in input order. Rows are not
sorted, filtered, deduplicated, or dropped — not even by `Статус` or
`Учёт в аналитике`.

---

## Requirements

- Python **3.11+** (developed and tested on 3.14).
- Runtime dependencies (installed automatically by `pip install -e .`):
  - `pandas>=3.1,<4` — tabular CSV/table transport;
  - `pdfplumber>=0.11.10,<0.12` — PDF table/text extraction;
  - `pypdf>=7,<8` — PDF page/text/metadata fallback.
- A local virtual environment is recommended (`.venv/`, already gitignored).

---

## Install and run

### Create the virtual environment

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
```

`pip install -e .` installs the runtime dependencies from
[`pyproject.toml`](pyproject.toml). An equivalent explicit list is kept in
[`requirements.txt`](requirements.txt) for environments that prefer
`pip install -r requirements.txt`.

### Run as a console script

```bash
.venv/bin/bank-parser -i data/input/T-Банк.csv -o out.csv
```

The installed entry point is `bank-parser = bank_parser.cli:main`.

### Run from the source tree without installing

```bash
PYTHONPATH=src .venv/bin/python -m bank_parser \
    -i data/input/T-Банк.csv \
    -o out.csv
```

`--bank` may be omitted when the file can be auto-detected (T-Bank is detected
from the filename or from its header columns); pass it explicitly to be safe:

```bash
.venv/bin/bank-parser \
    -i data/input/T-Банк.csv \
    -o out.csv \
    --bank tbank
```

### Behaviour

- On success the tool prints a one-line summary (`N transactions -> PATH`) and
  exits `0`.
- On failure it prints a clear message to stderr and exits non-zero.
- `--version` prints the package version.

---

## Project layout

```text
pyproject.toml              # packaging, runtime dependencies, console script
requirements.txt            # explicit dependency list (optional alternative)
README.md                   # this file
.gitignore
LICENSE
src/bank_parser/
    __init__.py             # public API re-exports + version
    __main__.py             # python -m bank_parser entry point
    models.py               # Transaction dataclass (the canonical model)
    readers.py              # encoding/delimiter/quoting-tolerant table reader
    writers.py              # canonical CSV writer (BOM, LF, 8 fields)
    cli.py                  # argument parsing, auto-detection, error handling
    banks/
        __init__.py         # bank registry, aliases, get_parser(), detect_bank()
        tbank.py            # T-Bank adapter (header mapping, date/amount parsing)
scripts/
    verify.py               # optional QA comparison harness (not a unit-test suite)
docs/                       # local-only notes: spec.md, architecture.md, code_style.md
.venv/                      # local virtual environment (gitignored)
```

`data/`, `docs/`, `.mnemon/`, `tmp/`, `.venv/` and Python caches are local-only
and are excluded by `.gitignore`; they are never committed. The architecture and
code-style notes for the multi-format (CSV + PDF) design live under `docs/` for
local reference.

---

## Adding a bank adapter

1. Create `src/bank_parser/banks/<bank>.py` and implement the adapter contract:

   ```python
   BANK_NAME = "<bank>"
   ALIASES = ("<bank>", "...")

   def parse_rows(rows: list[list[str]], *, source: str = "") -> list[Transaction]: ...
   def parse(path: str | Path) -> list[Transaction]: ...
   ```

   Reuse `bank_parser.readers.read_table()` (encoding, delimiter, quoting) and
   emit `bank_parser.models.Transaction` objects. Resolve columns by header
   name, not position. Keep money in `Decimal`, never `float`. Raise
   `ValueError` messages that include the 1-based data-row number when a cell
   cannot be parsed.

2. Register the adapter in `src/bank_parser/banks/__init__.py`:
   - add `"<bank>": "<bank>"` to `_REGISTRY`;
   - add the user-facing aliases to `_ALIASES`.

3. Optionally teach `detect_bank()` new filename/header markers so
   `--bank` can be omitted.

4. Try it explicitly first: `bank-parser ... --bank <bank>`. Add a QA
   comparison under `scripts/` if you have a trustworthy reference file.

The canonical model and writer stay unchanged; the adapter is the only
bank-specific code.

---

## Optional QA harness

`scripts/verify.py` is a standalone comparison harness — deliberately *not* a
unit-test suite. It runs the parser end-to-end, compares the generated CSV with
a handwritten reference semantically (treating missing trailing empty fields as
equal), checks canonical formatting on the generated file, and audits both
files against an oracle derived independently from the input export.

```bash
# Generate output for the default T-Bank fixture into tmp/ and compare it
python3 scripts/verify.py

# Compare any existing generated/reference pair (does not run the parser)
python3 scripts/verify.py --compare-only \
    --generated tmp/verify/Т-Банк.csv \
    --reference data/output/Т-Банк.csv
```

Exit codes: `0` pass, `1` mismatch, `2` harness error. It is optional and is
not required to use the parser.

---

## Limitations and notes

- **Only T-Bank is supported.** Other banks (and non-CSV inputs such as PDF)
  are out of scope for this milestone.
- **Handwritten reference files are hints, not byte-exact ground truth.** The
  reference outputs under `data/output/` were typed by hand and may contain
  manual errors (for example, a row that ends with 6 fields instead of 8
  because the trailing empty `comment` and placeholder were omitted). The
  generated output is clean and canonical; the QA harness tolerates and
  explains such reference typos rather than treating them as parser bugs.
- The `Статус` / `Учёт в аналитике` columns are read but not used for filtering
  in this milestone: every input transaction is included.
- The T-Bank fixture exercises only a subset of the tolerance rules above.
  Dot decimals, Unicode minus, thousands separators, alternative date formats,
  `cp1251`/tab/comma inputs, embedded delimiters/newlines, zero amounts and the
  currency/category fallbacks are implemented and were checked with synthetic
  inputs, but are not all present in the fixture.
- Output directories are not created automatically; the destination directory
  must exist.

---

## License

MIT — see [LICENSE](LICENSE).

## Not committed

Real bank data, handwritten reference files, local planning notes and scratch
output are deliberately kept local and are **not** part of this repository:
`data/`, `docs/`, `.mnemon/` and `tmp/` are ignored by `.gitignore`. The
repository contains only the parser code, `scripts/verify.py`, packaging
metadata, this README, `.gitignore` and the license.
