"""BibTeX ingestion: .bib file -> list[Reference] (plan §4.1)."""

from pathlib import Path

import bibtexparser
from bibtexparser.model import Entry

from cite_check.models import Reference
from cite_check.normalize import clean_text, extract_year, split_bibtex_authors

# BibTeX fields that describe the publication venue, in preference order.
_VENUE_FIELDS = ("journal", "booktitle", "publisher", "school", "institution", "howpublished")


def _field(entry: Entry, name: str) -> str | None:
    field = entry.fields_dict.get(name)
    if field is None:
        return None
    value = str(field.value).strip()
    return value or None


def _entry_to_reference(entry: Entry) -> Reference | None:
    title = _field(entry, "title")
    if title is None:
        return None

    venue = next((v for f in _VENUE_FIELDS if (v := _field(entry, f)) is not None), None)
    author_field = _field(entry, "author")
    year_field = _field(entry, "year")

    return Reference(
        key=entry.key,
        raw=entry.raw or "",
        title=clean_text(title),
        authors=split_bibtex_authors(author_field) if author_field else [],
        year=extract_year(year_field) if year_field else None,
        venue=clean_text(venue) if venue else None,
        doi=_field(entry, "doi"),
        source="bibtex",
    )


def parse_bibtex(path: str | Path) -> list[Reference]:
    """Parse a .bib file into references, skipping entries without a title."""
    library = bibtexparser.parse_file(str(path))  # type: ignore[attr-defined]
    refs = [ref for entry in library.entries if (ref := _entry_to_reference(entry)) is not None]
    return refs
