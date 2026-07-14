"""Input ingestion: BibTeX and PDF parsers producing list[Reference]."""

from cite_check.ingest.bibtex import parse_bibtex
from cite_check.ingest.pdf import parse_pdf

__all__ = ["parse_bibtex", "parse_pdf"]
