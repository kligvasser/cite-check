"""Build suggested fixes for MISMATCH results (plan §4.4)."""

import re

import bibtexparser
from bibtexparser.bibdatabase import BibDatabase
from bibtexparser.bparser import BibTexParser
from bibtexparser.bwriter import BibTexWriter

from cite_check.models import Reference, ScholarRecord, SuggestedFix

_ENTRY_TYPE_RE = re.compile(r"@(\w+)\s*\{")

# entry type -> BibTeX field that holds the venue
_VENUE_FIELD = {
    "article": "journal",
    "inproceedings": "booktitle",
    "incollection": "booktitle",
    "conference": "booktitle",
    "book": "publisher",
}


def _entry_type(ref: Reference) -> str:
    match = _ENTRY_TYPE_RE.search(ref.raw)
    return match.group(1).lower() if match else "misc"


def _bibtex_authors(authors: list[str]) -> str:
    return " and ".join(authors)


def _patch_original(
    ref: Reference, record: ScholarRecord, field_diffs: dict[str, tuple[str, str]]
) -> str | None:
    """Edit only the disputed fields of the original entry, keeping everything else
    (volume, pages, url, ...). None if the raw block can't be re-parsed."""
    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    try:
        entries = bibtexparser.loads(ref.raw, parser).entries
    except Exception:
        return None
    if len(entries) != 1:
        return None
    entry = entries[0]
    if "title" in field_diffs:
        entry["title"] = f"{{{record.title}}}"
    if "authors" in field_diffs and record.authors:
        entry["author"] = _bibtex_authors(record.authors)
    if "year" in field_diffs and record.year is not None:
        entry["year"] = str(record.year)
    if "doi" in field_diffs:
        entry.pop("doi", None)  # wrong DOI: dropping it beats keeping a false pointer
    database = BibDatabase()
    database.entries = [entry]
    writer = BibTexWriter()
    writer.order_entries_by = None
    writer.display_order = ["author", "title", "booktitle", "journal", "year"]
    return str(writer.write(database)).strip()


def build_corrected_bibtex(
    ref: Reference, record: ScholarRecord, field_diffs: dict[str, tuple[str, str]]
) -> str:
    """The entry with disputed fields taken from the found record."""
    patched = _patch_original(ref, record, field_diffs)
    if patched is not None:
        return patched
    entry_type = _entry_type(ref)
    title = record.title if "title" in field_diffs else ref.title
    authors = record.authors if "authors" in field_diffs else ref.authors
    year = record.year if "year" in field_diffs else ref.year
    venue = ref.venue or record.venue

    lines = [f"@{entry_type}{{{ref.key or 'unknown'},"]
    lines.append(f"  title = {{{title}}},")
    if authors:
        lines.append(f"  author = {{{_bibtex_authors(authors)}}},")
    if venue:
        field = _VENUE_FIELD.get(entry_type, "howpublished")
        lines.append(f"  {field} = {{{venue}}},")
    if year is not None:
        lines.append(f"  year = {{{year}}},")
    if ref.doi and "doi" not in field_diffs:
        lines.append(f"  doi = {{{ref.doi}}},")
    lines.append("}")
    return "\n".join(lines)


def build_fix(
    ref: Reference, record: ScholarRecord, field_diffs: dict[str, tuple[str, str]]
) -> SuggestedFix:
    corrected_fields: dict[str, str] = {}
    if "title" in field_diffs:
        corrected_fields["title"] = record.title
    if "authors" in field_diffs:
        corrected_fields["author"] = _bibtex_authors(record.authors)
    if "year" in field_diffs and record.year is not None:
        corrected_fields["year"] = str(record.year)

    note = "; ".join(
        f"{field}: {cited!r} -> {found!r}" for field, (cited, found) in field_diffs.items()
    )
    corrected_bibtex = (
        build_corrected_bibtex(ref, record, field_diffs) if ref.source == "bibtex" else None
    )
    return SuggestedFix(
        corrected_fields=corrected_fields,
        corrected_bibtex=corrected_bibtex,
        note=note,
    )
