# bank-parser

Convert Russian bank export files into a single, clean canonical transaction CSV.

`bank-parser` is a small Python CLI with a deliberately narrow dependency set.
It reads a bank's export file, maps it through a per-bank adapter into a common
`Transaction` model, and writes one canonical CSV that is easy to load into a
spreadsheet, database, or accounting tool.

The tool is deliberately boring: no network access, no binary floats for money
(`decimal.Decimal` only), and no hidden state. `pandas` is confined to tabular
CSV/table transport, and the PDF extraction path is built on `pdfplumber` (with
`pypdf` as a fallback) even though no PDF adapter is registered yet. The output
is byte-for-byte deterministic for a given input.

> Status: three CSV adapters are implemented — **T-Bank CSV**, **Sber CSV** and
> **Alfa-Bank CSV**. PDF statements are the next milestone: the extraction
> infrastructure is in place, but no PDF bank adapter is registered yet, so PDF
> input is rejected with a clear error.

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

| Bank       | Input                        | Adapter name | Fixture rows | Status    |
|------------|------------------------------|--------------|--------------|-----------|
| T-Bank     | T-Bank 17-column CSV export  | `tbank`      | 117          | Supported |
| Sber       | Sber 17-column CSV export    | `sber-csv`   | 16           | Supported |
| Alfa-Bank  | Alfa 16-column English CSV   | `alfa`       | 96           | Supported |

PDF statements are **not** supported yet: the extraction infrastructure exists,
but no PDF bank adapter is registered.

Supported aliases for the `--bank` option (case-insensitive):

| Bank       | Aliases |
|------------|---------|
| T-Bank     | `tbank`, `t-bank`, `т-банк`, `т банк` |
| Sber       | `sber-csv`, `sber`, `сбер`, `сбербанк` |
| Alfa-Bank  | `alfa`, `alpha`, `альфа`, `альфа-банк` |

### Bank detection

Detection is **filename-first**, then header-signature based:

- `tbank` / `t-bank` / `т-банк`, `sber` / `сбер` / `сбербанк`, and
  `alfa` / `alpha` / `альфа` in the filename select the adapter at high
  confidence (90).
- With a neutral filename, a distinctive **English Alfa header**
  (`operationDate`, `merchant`, `amount`, `type`) resolves to `alfa`.
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
filename (or, for Alfa, from its distinctive header). Pass it explicitly when
the filename is neutral, because the shared 17-column Russian header is
ambiguous between T-Bank and Sber:

```bash
.venv/bin/bank-parser -i data/input/T-Банк.csv   -o out.csv --bank tbank
.venv/bin/bank-parser -i data/input/Сбер_csv.csv -o out.csv --bank sber-csv
.venv/bin/bank-parser -i data/input/Альфа.CSV    -o out.csv --bank alfa
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
        normalizers.py      # TableNormalizer, TextNormalizer
        validation.py       # DefaultStatementValidator
        writers.py          # CanonicalCsvWriter
        peeks.py            # cheap CSV/PDF detection signals
        pdf_source.py       # PDF metadata acquisition (no PDF adapters yet)
    banks/
        __init__.py         # BANK_ADAPTERS, build_registry(), legacy facades
        tbank_csv.py        # TbankCsvMapper + TbankCsvAdapter
        sber_csv.py         # SberCsvAdapter (reuses TbankCsvMapper)
        alfa_csv.py         # AlfaCsvMapper + AlfaCsvAdapter
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

3. PDF adapters additionally provide a `PdfExtractor` (pdfplumber / pypdf) and,
   when needed, a custom normalizer or record predicate. The PDF source and
   detection peeks already exist; register the adapter the same way.

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

- **CSV adapters only: T-Bank, Sber and Alfa-Bank.** PDF statements are the
  next milestone; the extraction infrastructure (sources, ports, pipeline,
  detection) is in place, but no PDF adapter is registered, so PDF input is
  rejected with a clear error.
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
- The `Статус` / `Учёт в аналитике` columns are read but not used for filtering
  in this milestone: every input transaction is included.
- The local CSV fixtures exercise only a subset of the tolerance rules above.
  Dot decimals, Unicode minus, thousands separators, alternative date formats,
  `cp1251`/tab/comma inputs, embedded delimiters/newlines, zero amounts and the
  currency/category fallbacks are implemented and were checked with synthetic
  inputs, but are not all present in the T-Bank fixture. The Alfa fixture does
  cover the explicit `type` column and the `transactionDate` fallback path.
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
