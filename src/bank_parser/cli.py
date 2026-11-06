"""Command line interface for the ``bank_parser`` package."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from . import __version__
from .banks import detect_bank, get_parser, supported_banks
from .writers import write_transactions


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
        if args.bank:
            bank_name = args.bank
        else:
            bank_name = detect_bank(args.input)
        parse = get_parser(bank_name)
        transactions = parse(args.input)
        count = write_transactions(transactions, args.output)
    except Exception as exc:  # noqa: BLE001 - CLI boundary: report, do not trace
        print(f"bank-parser: error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(f"{count} transactions -> {Path(args.output)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
