"""Tests for bank registry, format-aware aliases and detection probes."""

from __future__ import annotations

from pathlib import Path

import pytest

from bank_parser.banks import BANK_ADAPTERS, build_registry, supported_banks
from bank_parser.banks.alfa_csv import AlfaCsvAdapter
from bank_parser.banks.ozon_pdf import OzonPdfAdapter
from bank_parser.banks.sber_pdf import SberPdfAdapter
from bank_parser.banks.tbank_csv import TbankCsvAdapter
from bank_parser.domain.models import InputFormat
from bank_parser.errors import UnsupportedBankError
from bank_parser.ports.detection import Detection, DetectionContext


class CsvPeekStub:
    def __init__(self, header):
        self._header = tuple(header)

    def header(self, path):
        return self._header


class PdfPeekStub:
    def __init__(self, first_page="", metadata=None):
        self._text = first_page
        self._metadata = metadata or {}

    def first_page_text(self, path):
        return self._text

    def metadata(self, path):
        return self._metadata


class FakePdfContext:
    def __init__(self, tokens=(), first_page=""):
        self._tokens = frozenset(tokens)
        self._first_page = first_page

    @property
    def filename_tokens(self):
        return self._tokens

    def pdf_first_page_text(self):
        return self._first_page


ALFA_HEADER = (
    "operationDate", "transactionDate", "accountName", "accountNumber",
    "cardName", "cardNumber", "merchant", "amount", "currency", "status",
    "category", "mcc", "type", "comment", "bonusValue", "bonusTitle",
)


def _csv_context(header, filename="neutral.csv"):
    return DetectionContext(
        Path(filename),
        csv_peek=CsvPeekStub(header),
        pdf_peek=PdfPeekStub(),
    )


def test_supported_banks_and_adapter_order():
    assert supported_banks() == ["alfa", "ozon", "sber", "tbank"]
    assert [adapter.name for adapter in BANK_ADAPTERS] == [
        "tbank", "alfa", "sber", "ozon"
    ]


def test_registry_has_alias_and_format_aware_resolution():
    registry = build_registry()
    assert registry.has_alias("sber") is True
    assert registry.has_alias("сбер") is True
    assert registry.has_alias("sber-csv") is False
    assert registry.has_alias("nope") is False
    assert registry.has_alias("") is False
    # ``sber`` is now PDF-only, so it resolves without a format and only the
    # PDF form is available.
    assert registry.resolve_alias("sber") is SberPdfAdapter
    assert registry.resolve_alias("sber", format=InputFormat.PDF) is SberPdfAdapter
    assert registry.resolve_alias("сбер", format=InputFormat.PDF) is SberPdfAdapter
    with pytest.raises(UnsupportedBankError):
        registry.resolve_alias("sber", format=InputFormat.CSV)
    with pytest.raises(UnsupportedBankError):
        registry.resolve_alias("sber-csv")


def test_registry_canonical_names_and_aliases_resolve():
    registry = build_registry()
    assert registry.resolve_alias("tbank") is TbankCsvAdapter
    assert registry.resolve_alias("alfa") is AlfaCsvAdapter
    assert registry.resolve_alias("ozon") is OzonPdfAdapter
    assert registry.resolve_alias("sber") is SberPdfAdapter
    assert registry.resolve_alias("sber-pdf") is SberPdfAdapter


def test_alfa_english_header_probes_at_70():
    context = _csv_context(ALFA_HEADER, filename="statement.csv")
    probe = AlfaCsvAdapter.probe(context)
    assert isinstance(probe, Detection)
    assert probe.confidence == 70
    assert probe.adapter_name == "alfa"
    assert TbankCsvAdapter.probe(context) is None


def test_sber_pdf_probe_filename_and_body_signature():
    filename = SberPdfAdapter.probe(FakePdfContext(tokens={"сбер"}))
    assert isinstance(filename, Detection) and filename.confidence == 90
    body = SberPdfAdapter.probe(
        FakePdfContext(first_page="Выписка по платёжному счёту. СберБанк.")
    )
    assert isinstance(body, Detection) and body.confidence == 85
    assert SberPdfAdapter.probe(FakePdfContext(first_page="unrelated")) is None


def test_ozon_pdf_probe_filename_body_and_purpose():
    filename = OzonPdfAdapter.probe(FakePdfContext(tokens={"ozon"}))
    assert isinstance(filename, Detection) and filename.confidence == 90
    body = OzonPdfAdapter.probe(
        FakePdfContext(first_page="ООО «ОЗОН Банк». Справка о движении средств")
    )
    assert isinstance(body, Detection) and body.confidence == 85
    purpose = OzonPdfAdapter.probe(
        FakePdfContext(first_page="Назначение платежа в документе")
    )
    assert isinstance(purpose, Detection) and purpose.confidence == 80
    assert OzonPdfAdapter.probe(FakePdfContext(first_page="unrelated")) is None


def test_sber_pdf_and_ozon_probes_are_mutually_exclusive():
    sber_context = FakePdfContext(
        first_page="Выписка по платёжному счёту. СберБанк."
    )
    ozon_context = FakePdfContext(first_page="ООО «ОЗОН Банк»")
    assert OzonPdfAdapter.probe(sber_context) is None
    assert SberPdfAdapter.probe(ozon_context) is None


@pytest.mark.skipif(
    not all(
        (Path("data/input") / name).exists()
        for name in ("T-Банк.csv", "Сбер_csv.csv", "Альфа.CSV", "Сбер.pdf", "Ozon.pdf")
    ),
    reason="real data/input fixtures are not present",
)
def test_detect_bank_real_fixtures():
    from bank_parser.banks import detect_bank

    assert detect_bank(Path("data/input/T-Банк.csv")) == "tbank"
    assert detect_bank(Path("data/input/Сбер_csv.csv")) == "tbank"
    assert detect_bank(Path("data/input/Альфа.CSV")) == "alfa"
    assert detect_bank(Path("data/input/Сбер.pdf")) == "sber"
    assert detect_bank(Path("data/input/Ozon.pdf")) == "ozon"
