# bank-parser

Convert Russian bank export files into a single, clean canonical transaction CSV.

`bank-parser` is a small Python CLI with a deliberately narrow dependency set.
It reads a bank's export file, maps it through a per-bank adapter into a common
`Transaction` model, and writes one canonical CSV that is easy to load into a
spreadsheet, database, or accounting tool.

The tool is deliberately boring: no network access, no binary floats for money
(`decimal.Decimal` only), and no hidden state. `pandas` is confined to tabular
CSV/table transport, and PDF statements are read with `pdfplumber` (text or
table extraction, with `pypdf` text extraction available as a fallback
strategy). The output is byte-for-byte deterministic for a given input.

> Status: all five known inputs are supported — **T-Bank CSV**, **Sber CSV**,
> **Alfa-Bank CSV**, **Sber PDF** and **Ozon PDF**. See
> [Supported banks](#supported-banks) for details.

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
- Bank auto-detection from the filename or a content signature (header/body
  text), with an explicit `--bank` override.
- Clear error messages that name the offending data row.

---

## Supported banks

| Bank       | Input                        | Adapter name | Fixture rows | Status    |
|------------|------------------------------|--------------|--------------|-----------|
| T-Bank     | T-Bank 17-column CSV export  | `tbank`      | 117          | Supported |
| Sber       | Sber 17-column CSV export    | `sber-csv`   | 16           | Supported |
| Alfa-Bank  | Alfa 16-column English CSV   | `alfa`       | 96           | Supported |
| Sber       | Sber PDF statement           | `sber-pdf`   | 50           | Supported |
| Ozon       | Ozon PDF statement           | `ozon`       | 47           | Supported |

All five inputs in `data/input/` are now supported.

Supported aliases for the `--bank` option (case-insensitive):

| Bank       | Aliases |
|------------|---------|
| T-Bank     | `tbank`, `t-bank`, `т-банк`, `т банк` |
| Sber       | `sber-csv`, `sber-pdf`, `sber`, `сбер`, `сбербанк` |
| Alfa-Bank  | `alfa`, `alpha`, `альфа`, `альфа-банк` |
| Ozon       | `ozon`, `озон`, `ozon-bank` |

`сбер` / `sber` / `сбербанк` are shared by the Sber CSV and Sber PDF adapters;
they resolve by input format (`.csv` → `sber-csv`, `.pdf` → `sber-pdf`).

### Bank detection

Detection is **filename-first**, then content-signature based:

- `tbank` / `t-bank` / `т-банк`, `sber` / `сбер` / `сбербанк`,
  `alfa` / `alpha` / `альфа`, and `ozon` / `озон` in the filename select the
  adapter at high confidence (90).
- With a neutral filename, a distinctive **English Alfa header**
  (`operationDate`, `merchant`, `amount`, `type`) resolves to `alfa`.
- With a neutral filename, a **Sber PDF body signature** on the first page
  (`Выписка по платёжному счёту` and `СберБанк`) resolves to `sber-pdf` at
  confidence 85.
- With a neutral filename, an **Ozon PDF body signature** on the first page
  (`ООО «ОЗОН Банк` or `Справка о движении средств`) resolves to `ozon` at
  confidence 85; the generic `Назначение платежа` heading resolves to `ozon`
  at confidence 80.
- A neutral **17-column Russian header** is shared by the T-Bank and Sber CSV
  exports, so it is deliberately ambiguous: the registry raises a detection
  error and asks for `--bank` instead of guessing.

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
| `date`     | Operation date, `DD/MM/YYYY` (T-Bank/Sber `Дата операции`; Alfa `operationDate`, falling back to `transactionDate` only when it is blank) |
| `merchant` | Description text (T-Bank/Sber `Описание`; Alfa `merchant`) |
| `amount`   | **Absolute** value, exactly 2 decimal digits, `.` separator (T-Bank/Sber signed `Сумма операции`; Alfa positive `amount` with the sign taken from `type`) |
| `currency` | T-Bank/Sber `Валюта операции`, falling back to `Валюта счёта`; Alfa `currency` (e.g. `RUR`), preserved and never converted |
| `category` | T-Bank/Sber `Категория по-умолчанию`, falling back to `Ваша категория`; Alfa `category` |
| `type`     | `Списание` / `Пополнение` — derived from the signed amount for T-Bank/Sber and from the explicit `type` column for Alfa; zero amounts are `Списание` |
| `comment`  | T-Bank/Sber `Сообщение`; Alfa `comment` (may be empty) |
| (8th)      | Always empty (trailing comma) |

One data row is written per input transaction, in input order. Rows are not
sorted, filtered, deduplicated, or dropped — not even by `Статус` /
`Учёт в аналитике` (T-Bank/Sber) or `status` (Alfa).

For the **Sber PDF** statement the values come from the line-oriented statement
text: the operation date, category and signed amount from the operation header
line; the merchant from the following description line (with the trailing
`Операция по карте/счету ****dddd` suffix stripped); a `+` amount becomes
`Пополнение` and any other amount `Списание`; the currency is `RUR` declared by
the adapter; the comment is empty. The processing date is ignored.

For the **Ozon PDF** statement the values come from the pdfplumber table
(5 columns): the operation timestamp in column 0 (time dropped); the signed
amount in column 3, cross-checked against the account-currency amount in
column 4 when that cell is non-empty; the category and merchant from ordered
`Назначение платежа` purpose rules on column 2 (SBP transfer recipient,
own-funds transfer, Ozon platform payment, card payment, tips); the currency is
`RUR` declared by the adapter; the comment is empty.

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

`--bank` may be omitted when the file's bank can be auto-detected from its
filename (or, for Alfa and the PDF adapters, from a content signature). Pass it
explicitly when the filename is neutral, because the shared 17-column Russian
header is ambiguous between T-Bank and Sber CSV:

```bash
.venv/bin/bank-parser -i data/input/T-Банк.csv   -o out.csv --bank tbank
.venv/bin/bank-parser -i data/input/Сбер_csv.csv -o out.csv --bank sber-csv
.venv/bin/bank-parser -i data/input/Альфа.CSV    -o out.csv --bank alfa
.venv/bin/bank-parser -i data/input/Сбер.pdf     -o out.csv --bank sber-pdf
.venv/bin/bank-parser -i data/input/Ozon.pdf     -o out.csv --bank ozon
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
    __init__.py             # public API re-exports + version + NullHandler
    __main__.py             # python -m bank_parser entry point
    cli.py                  # argparse + composition root
    application.py          # Application use-case facade (convert/read)
    pipeline.py             # StatementPipeline Template Method (CSV/PDF)
    registry.py             # BankRegistry, Source/Pipeline/Adapter factories
    errors.py               # BankParserError hierarchy
    models.py               # legacy facade re-exporting the domain model
    readers.py              # legacy read_table() facade
    writers.py              # legacy write_transactions() facade
    domain/
        models.py           # Transaction, Money, OperationType, SourceLocation
        raw.py              # raw/normalised records, tables, layouts
        parsing.py          # Russian date/amount parsers
        currency.py         # source-currency helper
    ports/
        source.py           # StatementSource, TableReader, peeks
        extraction.py       # PdfExtractor
        mapping.py          # RowMapper, DateParser, AmountParser
        adapter.py          # BankAdapter ABC + AdapterDependencies
        detection.py        # Detection, DetectionContext
        pipeline.py         # InputNormalizer, StatementValidator, CanonicalWriter
    adapters/
        csv_source.py       # pandas/stdlib CSV readers + CsvStatementSource
        pdf_source.py       # PDF metadata acquisition (pypdf)
        pdf_extractors.py   # pdfplumber text/table + pypdf extractors
        normalizers.py      # TableNormalizer, TextNormalizer
        validation.py       # DefaultStatementValidator
        writers.py          # CanonicalCsvWriter
        peeks.py            # cheap CSV/PDF detection signals
    banks/
        __init__.py         # BANK_ADAPTERS, build_registry(), legacy facades
        tbank_csv.py        # TbankCsvMapper + TbankCsvAdapter
        sber_csv.py         # SberCsvAdapter (reuses TbankCsvMapper)
        alfa_csv.py         # AlfaCsvMapper + AlfaCsvAdapter
        sber_pdf.py         # SberPdfMapper + SberPdfAdapter (line state machine)
        ozon_pdf.py         # OzonPdfMapper + OzonPdfAdapter (table + purpose rules)
        tbank.py            # legacy T-Bank facade (parse/parse_rows)
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

The parser is built around a fixed pipeline
(`acquire → extract → normalize → map → validate → write`). A new bank supplies
a `BankAdapter` (metadata, detection, collaborators) and a `RowMapper`; it does
not touch the pipeline, the writer or the CLI.

1. Create `src/bank_parser/banks/<bank>.py`:

   ```python
   class MyBankMapper:
       def __init__(self, date_parser, amount_parser): ...
       def map(self, document: NormalizedDocument) -> list[Transaction]: ...

   class MyBankAdapter(BankAdapter):
       name = "<bank>"
       aliases = ("<bank>", "...")
       formats = frozenset({InputFormat.CSV})
       required_headers = (...)

       @classmethod
       def probe(cls, ctx: DetectionContext) -> Detection | None: ...

       def create_mapper(self) -> RowMapper:
           return MyBankMapper(self._deps.date_parser, self._deps.amount_parser)
   ```

   Resolve columns by header name through `NormalizedTable.layout` (never by
   position), use the injected date/amount parsers, build `Money` /
   `Transaction.from_money`, and raise the location-aware `ParseError`
   subclasses. Keep money in `Decimal`, never `float`.

2. Register the adapter class in `BANK_ADAPTERS` in
   `src/bank_parser/banks/__init__.py`. Aliases and detection are derived from
   the class metadata; no separate alias map is needed. If a bank shares the
   exact header of an existing one (as Sber does with T-Bank), create a separate
   adapter that reuses the existing mapper, and keep the shared-header probe at
   the same confidence so a neutral filename ties and asks for `--bank` instead
   of guessing.

3. PDF adapters additionally provide a `PdfExtractor` from
   `adapters/pdf_extractors.py` (`PdfPlumberTextExtractor`,
   `PdfPlumberTableExtractor`, `PypdfTextExtractor`, or `FallbackExtractor`),
   plus a normalizer and a mapper (line state machine or table rows). The PDF
   source and detection peeks already exist; register the adapter the same way.

4. Try it explicitly first: `bank-parser ... --bank <bank>`. Add a QA
   comparison under `scripts/` if you have a trustworthy reference file.

The canonical model and writer stay unchanged; the adapter is the only
bank-specific code. Design details are in `docs/architecture.md` §16–17
(local-only).

---

## Optional QA harness

`scripts/verify.py` is a standalone comparison harness — deliberately *not* a
unit-test suite. It runs the parser end-to-end, compares the generated CSV with
a handwritten reference semantically (treating missing trailing empty fields as
equal), checks canonical formatting on the generated file, and audits both
files against an oracle derived independently from the input export.

```bash
# Generate output for the default T-Bank fixture into tmp/ and compare it
.venv/bin/python scripts/verify.py

# Compare any existing generated/reference pair (does not run the parser)
.venv/bin/python scripts/verify.py --compare-only \
    --generated tmp/verify/Т-Банк.csv \
    --reference data/output/Т-Банк.csv
```

Exit codes: `0` pass, `1` mismatch, `2` harness error. It is optional and is
not required to use the parser.

---

## Limitations and notes

- **Supported adapters: T-Bank CSV, Sber CSV, Alfa-Bank CSV, Sber PDF and
  Ozon PDF.** All five inputs in `data/input/` now convert; no registered-bank
  gaps remain for this repository's fixtures.
- **A neutral 17-column Russian CSV header is ambiguous.** The T-Bank and Sber
  exports share the same header, so a file without a recognizable bank name in
  its filename must be converted with an explicit `--bank tbank` or
  `--bank sber-csv`.
- **Handwritten reference files are hints, not byte-exact ground truth.** The
  reference outputs under `data/output/` were typed by hand and may contain
  manual errors (for example, a row that ends with 6 fields instead of 8
  because the trailing empty `comment` and placeholder were omitted). The
  generated output is clean and canonical; the QA harness tolerates and
  explains such reference typos rather than treating them as parser bugs.
- **The Sber PDF reference has six known manual discrepancies.** Compared with
  the statement's own header lines, `data/output/Сбер.csv` has one wrong
  category (row 8) and five wrong operation dates (rows 25, 28, 30, 31 and 41).
  The generated Sber PDF output follows the operation date printed on the PDF
  header, never the processing date; QA treats exactly these six differences as
  explained reference typos.
- **The Ozon PDF reference is handwritten and noisy.** `data/output/Ozon.csv`
  leaves `currency` blank on rows 2–47, deletes embedded newlines from merchant
  text (and sometimes keeps a `Получатель:` prefix), has four category
  inconsistencies, a type inconsistency on row 12 (reference `Пополнение` where
  the PDF amount is negative) and an amount typo on row 47 (`499.00` vs the
  PDF's `499.97`). The generated output is clean and canonical, so it
  intentionally differs from that reference at those points; QA explains every
  difference from the PDF's own table rows instead of matching the handwritten
  file byte-for-byte.
- The `Статус` / `Учёт в аналитике` columns are read but not used for filtering
  in this milestone: every input transaction is included.
- The local fixtures exercise only a subset of the tolerance rules above.
  Dot decimals, Unicode minus, thousands separators, alternative date formats,
  `cp1251`/tab/comma inputs, embedded delimiters/newlines, zero amounts and the
  currency/category fallbacks are implemented and were checked with synthetic
  inputs, but are not all present in the T-Bank fixture. The Alfa fixture does
  cover the explicit `type` column and the `transactionDate` fallback path.
- **Sber PDF extraction is text-based.** `data/input/Сбер.pdf` is 3 pages and
  pdfplumber finds no tables in it: the mapper is a line-oriented state machine
  over page text. Text extraction requires `pdfplumber`; `pypdf` is only a
  fallback and is not used for the supported Sber statement.
- **Ozon PDF extraction is table-based.** `data/input/Ozon.pdf` is 6 pages and
  pdfplumber returns one table per page (49 rows: 2 header rows plus 47 data
  rows); a record predicate keeps only rows that start with an operation
  timestamp. The purpose rules are ordered, and an unrecognized purpose raises
  a location-aware `ParseError` instead of being silently skipped.
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
