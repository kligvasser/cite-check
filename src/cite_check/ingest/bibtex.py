"""BibTeX ingestion: .bib file -> list[Reference] (plan §4.1).

Uses bibtexparser v1: the `scholarly` backend depends on it, and v1/v2 cannot
coexist (same module name), so the whole project pins <2.
"""

from pathlib import Path

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter

from cite_check.models import Reference
from cite_check.normalize import (
    clean_text,
    extract_arxiv_id,
    extract_url,
    extract_year,
    split_bibtex_authors,
)

# BibTeX fields that describe the publication venue, in preference order.
_VENUE_FIELDS = ("journal", "booktitle", "publisher", "school", "institution", "howpublished")


def _entry_raw(entry: dict[str, str]) -> str:
    """Serialize the entry back to a BibTeX block (v1 keeps no source text)."""
    database = BibDatabase()
    database.entries = [entry]
    return str(BibTexWriter().write(database)).strip()


def _entry_to_reference(entry: dict[str, str]) -> Reference | None:
    title = entry.get("title", "").strip()
    if not title:
        return None

    venue = next((entry[f].strip() for f in _VENUE_FIELDS if entry.get(f, "").strip()), None)
    author_field = entry.get("author", "").strip()
    year_field = entry.get("year", "").strip()
    doi = entry.get("doi", "").strip()
    eprint = entry.get("eprint", "").strip()
    if eprint and entry.get("archiveprefix", "").strip().lower() == "arxiv":
        eprint = f"arXiv:{eprint}"
    arxiv_id = extract_arxiv_id(
        eprint, entry.get("journal"), entry.get("url"), entry.get("note"), entry.get("howpublished")
    )
    url = extract_url(entry.get("url"), entry.get("howpublished"), entry.get("note"))

    return Reference(
        key=entry.get("ID"),
        raw=_entry_raw(entry),
        title=clean_text(title),
        authors=split_bibtex_authors(author_field) if author_field else [],
        year=extract_year(year_field) if year_field else None,
        venue=clean_text(venue) if venue else None,
        doi=doi or None,
        arxiv_id=arxiv_id,
        url=url,
        entry_type=entry.get("ENTRYTYPE", "").lower() or None,
        source="bibtex",
    )


def parse_bibtex(path: str | Path) -> list[Reference]:
    """Parse a .bib file into references, skipping entries without a title."""
    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    with open(path, encoding="utf-8") as fh:
        library = bibtexparser.load(fh, parser)
    refs = [ref for entry in library.entries if (ref := _entry_to_reference(entry)) is not None]
    return refs
