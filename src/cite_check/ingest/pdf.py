"""Heuristic PDF ingestion: text -> references section -> entries (plan §4.1, phase A).

Heuristics can't beat a trained parser; for hard PDFs use ``--parser grobid``.
The raw string is always preserved on the Reference so users can spot parse failures.
"""

import re
from pathlib import Path

from cite_check.models import Reference
from cite_check.normalize import clean_text, extract_year

_HEADING_RE = re.compile(
    r"^\s*(?:[0-9]{1,2}\.?\s+|[IVXLC]+\.?\s+)?"
    r"(references|bibliography|works cited|literature cited)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_TAIL_RE = re.compile(
    r"^\s*(appendix|acknowledg\w*|supplementary)\b.*$", re.IGNORECASE | re.MULTILINE
)

_BRACKET_MARKER_RE = re.compile(r"\[\d{1,3}\]\s")
_NUMBER_MARKER_RE = re.compile(r"(?m)^\s*\d{1,3}\.\s+")
_APA_START_RE = re.compile(r"(?m)^(?=[A-Z][^\n]{0,150}?\((?:1[89]\d{2}|20\d{2})[a-z]?\))")

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;]+)", re.IGNORECASE)
_QUOTED_TITLE_RE = re.compile(r"[\"“]([^\"”]{10,})[\"”]")
_APA_YEAR_RE = re.compile(r"\((1[89]\d{2}|20\d{2})[a-z]?\)\.?\s*")
# split on sentence-ish boundaries without breaking "J. Smith" initials
_SEGMENT_SPLIT_RE = re.compile(r"(?<=[a-z\)\"”])\.\s+")


def extract_text(path: str | Path) -> str:
    import fitz  # pymupdf — lazy so text-level functions stay importable without it

    with fitz.open(str(path)) as doc:
        return "\n".join(page.get_text() for page in doc)


def find_references_section(text: str) -> str:
    """Return the text after the last references-style heading, trimmed of appendices."""
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        raise ValueError("No references/bibliography section found in the PDF text.")
    section = text[matches[-1].end() :]
    tail = _TAIL_RE.search(section)
    if tail:
        section = section[: tail.start()]
    return section.strip()


def _slice_at(text: str, starts: list[int]) -> list[str]:
    ends = starts[1:] + [len(text)]
    return [text[a:b] for a, b in zip(starts, ends, strict=True)]


def split_references(section: str) -> list[str]:
    """Split a references section into individual raw reference strings."""
    markers = list(_BRACKET_MARKER_RE.finditer(section))
    if len(markers) >= 2:  # IEEE style: [1] ... [2] ...
        starts = [m.start() for m in markers]
        chunks = _slice_at(section, starts)
    elif len(list(_NUMBER_MARKER_RE.finditer(section))) >= 2:  # "1. ..." style
        marks = [m.start() for m in _NUMBER_MARKER_RE.finditer(section)]
        chunks = _slice_at(section, marks)
    elif "\n\n" in section:  # blank-line separated
        chunks = re.split(r"\n\s*\n", section)
    else:  # APA-ish: new entry starts with "Author, A. ... (year)"
        marks = [m.start() for m in _APA_START_RE.finditer(section)]
        chunks = _slice_at(section, marks) if len(marks) >= 2 else [section]
    cleaned = [clean_text(c.replace("\n", " ")) for c in chunks]
    return [c for c in cleaned if len(c) > 20]


def _parse_authors(author_part: str) -> list[str]:
    author_part = re.sub(r"^\s*\[\d+\]\s*|^\s*\d{1,3}\.\s*", "", author_part)
    parts = re.split(r",\s*(?:and\s+)?|\s+and\s+|\s*&\s*", author_part)
    authors: list[str] = []
    for part in parts:
        part = part.strip(" .")
        if not part or part.lower() in ("et al", "al"):
            continue
        if not re.search(r"[a-z]", part):  # initials-only fragment like "N"
            # glue it onto the previous surname if any ("Vaswani", "A" -> "A Vaswani")
            if authors and len(part) <= 3:
                authors[-1] = f"{part} {authors[-1]}"
            continue
        authors.append(part)
    return authors


def parse_reference_string(raw: str, index: int) -> Reference | None:
    """Best-effort parse of one free-form reference string."""
    doi_match = _DOI_RE.search(raw)
    body = _DOI_RE.sub("", raw)
    stripped = re.sub(r"^\s*\[\d+\]\s*|^\s*\d{1,3}\.\s*", "", body).strip()

    title: str | None = None
    authors: list[str] = []
    venue: str | None = None

    apa = _APA_YEAR_RE.search(stripped)
    quoted = _QUOTED_TITLE_RE.search(stripped)
    if quoted:  # "Title in quotes" style
        title = quoted.group(1).strip(" .,")
        authors = _parse_authors(stripped[: quoted.start()])
        venue = stripped[quoted.end() :].strip(" .,") or None
    elif apa:  # Author, A. (2016). Title. Venue.
        authors = _parse_authors(stripped[: apa.start()])
        rest = stripped[apa.end() :]
        segments = _SEGMENT_SPLIT_RE.split(rest)
        title = segments[0].strip(" .,") if segments else None
        venue = segments[1].strip(" .,") if len(segments) > 1 else None
    else:  # A. Author, B. Author. Title of the paper. Venue, year.
        segments = _SEGMENT_SPLIT_RE.split(stripped)
        if len(segments) >= 2:
            # the title is usually the longest early segment
            title_idx = max(range(min(4, len(segments))), key=lambda i: len(segments[i]))
            title = segments[title_idx].strip(" .,")
            authors = _parse_authors(". ".join(segments[:title_idx]))
            venue = segments[title_idx + 1].strip(" .,") if title_idx + 1 < len(segments) else None

    if not title or len(title) < 5:
        return None
    if venue:
        venue = re.sub(r"^(?:in|In)\s+", "", venue)
        venue = re.sub(r"[,\s]*(?:1[89]\d{2}|20\d{2}).*$", "", venue).strip() or None

    return Reference(
        key=f"ref-{index}",
        raw=raw,
        title=title,
        authors=authors,
        year=extract_year(raw),
        venue=venue,
        doi=doi_match.group(1).rstrip(".") if doi_match else None,
        source="pdf",
    )


def parse_pdf_text(text: str) -> list[Reference]:
    section = find_references_section(text)
    raw_refs = split_references(section)
    refs = [parse_reference_string(raw, i) for i, raw in enumerate(raw_refs, start=1)]
    parsed = [r for r in refs if r is not None]
    # arXiv ids double as verifiable identifiers; keep them in raw for now (v1)
    return parsed


def parse_pdf(path: str | Path) -> list[Reference]:
    """Parse a paper PDF into references via text heuristics."""
    return parse_pdf_text(extract_text(path))
