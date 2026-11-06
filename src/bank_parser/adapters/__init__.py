"""Concrete I/O adapters for CSV/PDF sources, normalisation, validation and writing.

This package must not import pandas, pdfplumber or pypdf on package import.
Heavy-library imports live inside the individual adapter methods (or in
``adapters/csv_source.py``'s lazy ``read`` implementation) so that
``bank_parser`` and ``--help`` stay light.  Import concrete adapters from their
modules, not from this package.
"""

from __future__ import annotations

__all__: list[str] = []
