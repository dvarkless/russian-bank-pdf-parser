# bank-parser 1.0.0

[English version](README.en.md) | **Русская версия**

Преобразует выписки российских банков (CSV и PDF) в один канонический CSV-файл.

`bank-parser` — небольшой Python-CLI с минимальным набором зависимостей. Он
читает файл выписки, пропускает его через адаптер конкретного банка в общую
модель `Transaction` и записывает единый CSV, который удобно открыть в таблице,
загрузить в базу или использовать в бухгалтерии.

Деньги обрабатываются только через `decimal.Decimal` (без двоичных чисел с
плавающей точкой). `pandas` используется только как транспорт для табличных
данных, PDF читаются через `pdfplumber` (таблицы и текст), `pypdf` доступен как
резервный извлекатель текста. Для одного и того же входа результат
детерминирован.

> Статус: поддержаны все пять известных входных файлов — **T-Bank CSV**,
> **Сбер CSV**, **Альфа-Банк CSV**, **Сбер PDF** и **Ozon PDF**. Подробности в
> разделе [Поддерживаемые банки](#поддерживаемые-банки).

---

## Возможности

- Поиск колонок по имени заголовка, а не по позиции: порядок колонок не важен,
  лишние колонки игнорируются.
- Терпимость к кодировкам: `utf-8-sig`, `utf-8`, `cp1251`.
- Терпимость к разделителям: `;`, `,`, табуляция; определяется автоматически.
- Стандартные кавычки CSV, включая поля с разделителем или переводом строки
  внутри; поддерживаются CRLF и LF.
- Терпимость к суммам: десятичная запятая или точка, юникодный минус, неразрывные
  и тонкие пробелы в тысячах, символы валют.
- Автоопределение банка по имени файла или сигнатуре содержимого (заголовок
  CSV / текст первой страницы PDF); можно указать банк явно через `--bank`.
- Понятные ошибки с указанием файла, страницы и номера строки.

---

## Поддерживаемые банки

| Банк | Вход | Имя адаптера | Строк в фикстуре | Статус |
|---|---|---|---|---|
| T-Bank | CSV-выписка, 17 колонок | `tbank` | 117 | Поддержан |
| Сбер | CSV-выписка, 17 колонок | `sber-csv` | 16 | Поддержан |
| Альфа-Банк | CSV-выписка, 16 английских колонок | `alfa` | 96 | Поддержан |
| Сбер | PDF-выписка | `sber-pdf` | 50 | Поддержан |
| Ozon | PDF-выписка | `ozon` | 47 | Поддержан |

Все пять файлов из `data/input/` поддерживаются.

Псевдонимы для `--bank` (регистр не важен):

| Банк | Псевдонимы |
|---|---|
| T-Bank | `tbank`, `t-bank`, `т-банк`, `т банк` |
| Сбер | `sber-csv`, `sber-pdf`, `sber`, `сбер`, `сбербанк` |
| Альфа-Банк | `alfa`, `alpha`, `альфа`, `альфа-банк` |
| Ozon | `ozon`, `озон`, `ozon-bank` |

Псевдонимы `сбер` / `sber` / `сбербанк` общие для CSV- и PDF-адаптеров Сбера:
формат определяется по расширению файла (`.csv` → `sber-csv`,
`.pdf` → `sber-pdf`).

### Определение банка

Банк определяется в таком порядке: имя файла (высокая уверенность), сигнатура
содержимого (текст первой страницы PDF или заголовок CSV), затем слабые
признаки. Если имя файла нейтральное, а заголовок CSV совпадает у T-Bank и
Сбера (одинаковые 17 колонок), адаптер не угадывает: выбрасывается
`DetectionError` с просьбой указать `--bank tbank` или `--bank sber-csv`.

Добавление нового банка не меняет CLI и канонический writer — см.
[Добавление адаптера банка](#добавление-адаптера-банка).

---

## Канонический формат вывода

Каждый выходной файл записывается строго так:

| Свойство | Значение |
|---|---|
| Кодировка | UTF-8 **с BOM** (`utf-8-sig`) |
| Переводы строк | `\n` (LF), без хвостовых пробелов, один финальный перевод строки |
| Разделитель | `,` |
| Колонки | 8 полей, первой идёт строка заголовка |

Строка заголовка (обратите внимание на запятую в конце: 8-е поле — всегда пустой
заполнитель, соответствующий установленному шаблону):

```text
date,merchant,amount,currency,category,type,comment,
```

| Колонка | Источник / правило |
|---|---|
| `date` | Дата операции `DD/MM/YYYY` (T-Bank/Сбер — `Дата операции`; Альфа — `operationDate`, `transactionDate` только если первая пустая) |
| `merchant` | Описание (T-Bank/Сбер — `Описание`; Альфа — `merchant`) |
| `amount` | **Абсолютная** сумма, ровно 2 знака после точки, разделитель `.` (T-Bank/Сбер — знаковая `Сумма операции`; Альфа — положительная `amount`, знак берётся из `type`) |
| `currency` | T-Bank/Сбер — `Валюта операции`, иначе `Валюта счёта`; Альфа — `currency` (например, `RUR`), без конвертации |
| `category` | T-Bank/Сбер — `Категория по-умолчанию`, иначе `Ваша категория`; Альфа — `category` |
| `type` | `Списание` / `Пополнение`: по знаку суммы у T-Bank/Сбера, по явной колонке `type` у Альфы; ноль считается `Списание` |
| `comment` | T-Bank/Сбер — `Сообщение`; Альфа — `comment` (может быть пустым) |
| 8-е поле | Всегда пустое (запятая в конце) |

На каждую входную операцию пишется одна строка в исходном порядке. Сортировка,
фильтрация, дедупликация и отбрасывание строк не выполняются — даже по
`Статус` / `Учёт в аналитике` (T-Bank/Сбер) или `status` (Альфа).

**Сбер PDF.** Значения берутся из текста выписки: дата операции, категория и
знаковая сумма — из строки-заголовка операции; merchant — из следующей строки
описания (суффикс `Операция по карте/счету ****dddd` отбрасывается); сумма со
знаком `+` → `Пополнение`, любая другая → `Списание`; валюта `RUR` объявлена
адаптером; комментарий пустой. Дата обработки игнорируется.

**Ozon PDF.** Значения берутся из таблицы pdfplumber (5 колонок): отметка
времени в колонке 0 (время отбрасывается); знаковая сумма в колонке 3,
сверяется с суммой в валюте счёта в колонке 4, если она непустая; категория и
merchant — по упорядоченным правилам для `Назначение платежа` в колонке 2
(перевод через СБП, перевод собственных средств, оплата на платформе Ozon,
оплата картой, чаевые); валюта `RUR` объявлена адаптером; комментарий пустой.

---

## Требования

- Python **3.11+** (разработано и проверено на 3.14).
- Зависимости времени выполнения (ставятся через `pip install -e .`):
  - `pandas>=3.1,<4` — табличный транспорт CSV/таблиц;
  - `pdfplumber>=0.11.10,<0.12` — извлечение таблиц и текста из PDF;
  - `pypdf>=7,<8` — резервное чтение страниц/текста/метаданных PDF.
- Рекомендуется локальное виртуальное окружение (`.venv/`, уже в `.gitignore`).

---

## Установка и запуск

### Создание виртуального окружения

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/pip install -e .
```

`pip install -e .` ставит зависимости из [`pyproject.toml`](pyproject.toml).
Их же можно поставить из [`requirements.txt`](requirements.txt):

```bash
.venv/bin/pip install -r requirements.txt
```

Для запуска тестов установите dev-дополнение:

```bash
.venv/bin/pip install -e ".[dev]"
```

### Запуск как консольная команда

```bash
.venv/bin/bank-parser -i data/input/T-Банк.csv -o out.csv
```

Установленная точка входа: `bank-parser = bank_parser.cli:main`.

### Запуск из исходников без установки

```bash
PYTHONPATH=src .venv/bin/python -m bank_parser \
    -i data/input/T-Банк.csv \
    -o out.csv
```

Если имя файла не содержит названия банка, укажите его явно. Общий 17-колоночный
заголовок T-Bank и Сбера неоднозначен:

```bash
.venv/bin/bank-parser -i data/input/T-Банк.csv   -o out.csv --bank tbank
.venv/bin/bank-parser -i data/input/Сбер_csv.csv -o out.csv --bank sber-csv
.venv/bin/bank-parser -i data/input/Альфа.CSV    -o out.csv --bank alfa
.venv/bin/bank-parser -i data/input/Сбер.pdf     -o out.csv --bank sber-pdf
.venv/bin/bank-parser -i data/input/Ozon.pdf     -o out.csv --bank ozon
```

### Поведение

- При успехе печатается строка `N transactions -> PATH`, код возврата `0`.
- При ошибке печатается понятное сообщение в stderr, код возврата ненулевой.
- `--version` печатает версию пакета, `--help` — справку.
- Каталог для выходного файла должен существовать: writer его не создаёт.

---

## Структура проекта

```text
pyproject.toml              # упаковка, runtime/dev-зависимости, консольная команда
requirements.txt            # явный список runtime-зависимостей
README.md                   # русская документация (по умолчанию)
README.en.md                # английская документация
.gitignore
LICENSE
src/bank_parser/
    __init__.py             # публичный API, версия, NullHandler
    __main__.py             # python -m bank_parser
    cli.py                  # argparse и composition root
    application.py          # фасад Application (convert/read)
    pipeline.py             # StatementPipeline (Template Method, CSV/PDF)
    registry.py             # BankRegistry, фабрики Source/Pipeline/Adapter
    errors.py               # иерархия BankParserError
    models.py               # фасад доменной модели
    readers.py              # фасад read_table()
    writers.py              # фасад write_transactions()
    domain/
        models.py           # Transaction, Money, OperationType, SourceLocation
        raw.py              # сырые/нормализованные записи, таблицы, layout
        parsing.py          # парсеры российских дат и сумм
        currency.py         # работа с кодом валюты источника
    ports/
        source.py           # StatementSource, TableReader, peeks
        extraction.py       # PdfExtractor
        mapping.py          # RowMapper, DateParser, AmountParser
        adapter.py          # BankAdapter (ABC) + AdapterDependencies
        detection.py        # Detection, DetectionContext
        pipeline.py         # InputNormalizer, StatementValidator, CanonicalWriter
    adapters/
        csv_source.py       # pandas/stdlib CSV-ридеры + CsvStatementSource
        pdf_source.py       # метаданные PDF через pypdf
        pdf_extractors.py   # pdfplumber text/table + pypdf extractors
        normalizers.py      # TableNormalizer, TextNormalizer
        validation.py       # DefaultStatementValidator
        writers.py          # CanonicalCsvWriter
        peeks.py            # дешёвые сигналы для определения банка
    banks/
        __init__.py         # BANK_ADAPTERS, build_registry(), фасады
        tbank_csv.py        # TbankCsvMapper + TbankCsvAdapter
        sber_csv.py         # SberCsvAdapter (переиспользует TbankCsvMapper)
        alfa_csv.py         # AlfaCsvMapper + AlfaCsvAdapter
        sber_pdf.py         # SberPdfMapper + SberPdfAdapter (state machine)
        ozon_pdf.py         # OzonPdfMapper + OzonPdfAdapter (таблица + правила)
        tbank.py            # фасад T-Bank (parse/parse_rows)
tests/                      # unit-тесты pytest (inline-данные + tmp_path)
scripts/
    verify.py               # сравнение с фикстурами
docs/                       # локальные заметки: spec.md, architecture.md, code_style.md
.venv/                      # локальное окружение (в .gitignore)
```

`data/`, `docs/`, `.mnemon/`, `tmp/`, `.venv/` и кэши Python — локальные и не
коммитятся. Архитектурные заметки лежат в `docs/`.

---

## Архитектура

Обработка идёт по фиксированному конвейеру (Template Method):

```text
acquire → extract → normalize → map → validate → write
```

Слои: `domain` (значения и правила), `ports` (протоколы/ABC), `adapters`
(CSV/PDF-чтение, нормализация, валидация, writer), `banks` (адаптеры банков),
`pipeline`/`registry`/`application`/`cli` (сборка и запуск). Банк-специфичен
только адаптер; writer и CLI не меняются при добавлении банка.

---

## Добавление адаптера банка

1. Создайте `src/bank_parser/banks/<bank>.py` с `RowMapper` и `BankAdapter`:

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

   Колонки ищите по имени через `NormalizedTable.layout`, деньги держите в
   `Decimal`, ошибки оборачивайте в `ParseError` с локацией.

2. Зарегистрируйте класс в `BANK_ADAPTERS` в
   `src/bank_parser/banks/__init__.py`.

3. Для PDF-адаптера добавьте `PdfExtractor` из `adapters/pdf_extractors.py`
   (`PdfPlumberTextExtractor`, `PdfPlumberTableExtractor`, `PypdfTextExtractor`
   или `FallbackExtractor`) и при необходимости свой normalizer/mapper.

4. Проверьте явно: `bank-parser ... --bank <bank>`. При наличии эталонного файла
   добавьте сравнение в `scripts/`.

Каноническая модель и writer не меняются; банк-специфичен только адаптер.

---

## Тестирование

### Unit-тесты

```bash
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest
```

Тесты лежат в [`tests/`](tests) и используют pytest с inline-данными и
`tmp_path`; локальные файлы `data/` не требуются. Покрыты доменные значения и
парсеры, CSV-ридеры/writer, нормализация/валидация, все пять мапперов банков,
реестр/определение банка, конвейер/Application и CLI.

### Проверка на фикстурах

`scripts/verify.py` — отдельный сквозной harness (не unit-тесты). Он запускает
парсер, сравнивает результат с рукописным эталоном семантически (недостающие
пустые хвостовые поля считаются равными), проверяет канонический формат и
сверяет оба файла с независимым оракулом из входной выписки.

```bash
# T-Bank: сгенерировать результат в tmp/ и сравнить
.venv/bin/python scripts/verify.py

# Сравнить готовую пару файлов
.venv/bin/python scripts/verify.py --compare-only \
    --generated tmp/verify/Т-Банк.csv \
    --reference data/output/Т-Банк.csv
```

Ожидаемые количества строк и SHA-256 сгенерированных файлов для локальных
фикстур:

| Фикстура | Строк | SHA-256 |
|---|---|---|
| `data/input/T-Банк.csv` | 117 | `070b791241d0a6f468a6b212d98caaabc14c6ef1c82fa9057e8b671cce045c08` |
| `data/input/Сбер_csv.csv` | 16 | `c71b1c1a68c1e7ae9fae49983d4ba656def5e33a319f66acbe8c6b71aeb594f0` |
| `data/input/Альфа.CSV` | 96 | `d8709a291b76d1e455bdb5a4a325797a06fcf68a218e02826b4aa71608edee49` |
| `data/input/Сбер.pdf` | 50 | `aa3e267d4de1787eb7ac8f39913031ea07e057e1a6560a6765a3aa92d24bcf08` |
| `data/input/Ozon.pdf` | 47 | `790e0f1edca10dc4ed80a5485579e6e716c762b30cf435d80f31de319a7c6df1` |

Коды возврата `verify.py`: `0` — успех, `1` — расхождение, `2` — ошибка harness.

---

## Ограничения и примечания

- **Поддержаны адаптеры T-Bank CSV, Сбер CSV, Альфа-Банк CSV, Сбер PDF и
  Ozon PDF.** Все пять файлов из `data/input/` преобразуются.
- **Нейтральный 17-колоночный русский CSV неоднозначен.** У T-Bank и Сбера
  одинаковый заголовок, поэтому файл без названия банка в имени нужно
  обрабатывать с явным `--bank tbank` или `--bank sber-csv`.
- **Рукописные эталоны — подсказка, а не побайтовая истина.** Файлы в
  `data/output/` набраны вручную и могут содержать ошибки. Генератор выдаёт
  чистый канонический результат; QA объясняет расхождения как опечатки
  эталона.
- **В эталоне Сбер PDF шесть известных опечаток.** По сравнению с заголовками
  самой выписки в `data/output/Сбер.csv` неверна категория в строке 8 и даты в
  строках 25, 28, 30, 31 и 41. Генератор использует дату операции из PDF, а не
  дату обработки; эти шесть расхождений объяснены.
- **Эталон Ozon PDF шумный.** В `data/output/Ozon.csv` валюта пуста в строках
  2–47, из merchant-строк удалены переводы строк (иногда сохранён префикс
  `Получатель:`), есть четыре несогласованности категорий, ошибка типа в
  строке 12 и суммы в строке 47 (`499.00` вместо `499.97`). Генератор выдаёт
  чистый результат и намеренно отличается в этих местах; QA объясняет каждое
  расхождение по таблице PDF.
- Колонки `Статус` / `Учёт в аналитике` читаются, но не фильтруют строки:
  включаются все операции.
- Локальные фикстуры покрывают не все правила терпимости. Десятичная точка,
  юникодный минус, разделители тысяч, альтернативные форматы дат, `cp1251`,
  табуляция, встроенные разделители/переводы строк, нулевые суммы и fallback
  валюты/категории реализованы и проверены синтетическими тестами, но не все
  присутствуют в T-Bank-фикстуре. Альфа-фикстура покрывает явный `type` и
  fallback `transactionDate`.
- **Сбер PDF извлекается из текста.** В `data/input/Сбер.pdf` 3 страницы,
  pdfplumber не находит таблиц: маппер — построчный state machine. Нужен
  `pdfplumber`; `pypdf` — только резерв и для поддерживаемой выписки не
  используется.
- **Ozon PDF извлекается из таблиц.** В `data/input/Ozon.pdf` 6 страниц, по
  одной таблице на страницу (49 строк: 2 заголовка + 47 данных); предикат
  оставляет только строки с отметкой времени. Правила назначения
  упорядочены, неизвестное назначение даёт `ParseError` с локацией, а не
  молча пропускается.
- Выходной каталог не создаётся автоматически.

---

## Лицензия

MIT — см. [LICENSE](LICENSE).

## Что не коммитится

Реальные банковские данные, рукописные эталоны, локальные заметки и временный
вывод не входят в репозиторий: `data/`, `docs/`, `.mnemon/` и `tmp/` исключены
через `.gitignore`. В репозитории — код парсера, unit-тесты в `tests/`,
`scripts/verify.py`, упаковка, оба README, `.gitignore` и лицензия.

---

**Русская версия** · [English version](README.en.md)
