"""Command line interface and composition root for ``bank_parser``."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Sequence

from . import __version__
from .banks import supported_banks
from .errors import BankParserError

if TYPE_CHECKING:
    from .application import Application

__all__ = ["build_application", "build_parser", "main"]

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for the ``bank-parser`` CLI."""
    parser = argparse.ArgumentParser(
        prog="bank-parser",
        description=(
            "Convert a bank export file into the canonical transaction CSV "
            "(UTF-8 with BOM, LF, DD/MM/YYYY, absolute decimal amounts)."
        ),
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        metavar="PATH",
        help="input bank export file",
    )
    parser.add_argument(
        "-o",
        "--output",
        required=True,
        metavar="PATH",
        help="output canonical CSV file",
    )
    parser.add_argument(
        "-b",
        "--bank",
        default=None,
        metavar="NAME",
        help=(
            "bank parser to use; auto-detected when omitted "
            f"(supported: {', '.join(supported_banks())})"
        ),
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    return parser


def build_application() -> Application:
    """Build the fully wired application (the composition root).

    Heavy adapter modules (pandas/pdfplumber/pypdf) are imported here, after
    argparse has handled ``--help``/``--version``, so those paths stay light.

    Returns:
        A configured :class:`~bank_parser.application.Application`.
    """
    from .adapters.csv_source import (
        CsvStatementSource,
        PandasTableReader,
    )
    from .adapters.peeks import PandasCsvPeek, PdfPlumberPdfPeek
    from .adapters.pdf_source import (
        PdfStatementSource,
        PypdfMetadataReader,
    )
    from .adapters.validation import DefaultStatementValidator
    from .adapters.writers import CanonicalCsvWriter
    from .application import Application
    from .banks import BANK_ADAPTERS
    from .domain.parsing import RussianAmountParser, RussianDateParser
    from .ports.adapter import AdapterDependencies
    from .registry import (
        AdapterFactory,
        BankRegistry,
        PipelineFactory,
        SourceFactory,
    )

    deps = AdapterDependencies(
        date_parser=RussianDateParser(),
        amount_parser=RussianAmountParser(),
        validator=DefaultStatementValidator(),
    )
    reader = PandasTableReader()
    source_factory = SourceFactory(
        csv=CsvStatementSource(reader),
        pdf=PdfStatementSource(PypdfMetadataReader()),
    )
    pipeline_factory = PipelineFactory(
        source_factory=source_factory,
        writer=CanonicalCsvWriter(),
        validator=deps.validator,
    )
    factory = AdapterFactory(
        BankRegistry(BANK_ADAPTERS),
        deps=deps,
        pipeline_factory=pipeline_factory,
        csv_peek=PandasCsvPeek(reader),
        pdf_peek=PdfPlumberPdfPeek(),
    )
    return Application(factory)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI.

    Args:
        argv: Argument list without the program name; defaults to
            :data:`sys.argv` when ``None``.

    Returns:
        Process exit code: ``0`` on success, ``1`` on handled errors.
    """
    args = build_parser().parse_args(argv)

    try:
        application = build_application()
        result = application.convert(
            Path(args.input),
            Path(args.output),
            bank=args.bank,
        )
    except (BankParserError, OSError) as exc:
        print(f"bank-parser: error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report, never trace
        logger.debug("unexpected failure", exc_info=True)
        print(
            f"bank-parser: error: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        f"{result.transactions_written} transactions -> {result.output_path}"
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
