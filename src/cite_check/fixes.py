"""Build suggested fixes for MISMATCH results (plan §4.4)."""

import re

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


def build_corrected_bibtex(
    ref: Reference, record: ScholarRecord, field_diffs: dict[str, tuple[str, str]]
) -> str:
    """Regenerate the entry, taking disputed fields from the Scholar record."""
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
    if ref.doi:
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
