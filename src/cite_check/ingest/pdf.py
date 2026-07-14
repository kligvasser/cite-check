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
    r"^\s*(appendix|acknowledg\w*|supplementary|(?:neurips\s+paper\s+)?checklist)\b.*$",
    re.IGNORECASE | re.MULTILINE,
)

_BRACKET_MARKER_RE = re.compile(r"\[(\d{1,3})\]\s")
_NUMBER_MARKER_RE = re.compile(r"(?m)^\s*(\d{1,3})\.\s+")
_MAX_CHUNK_CHARS = 800  # real references are short; longer chunks are appendix bleed-through
# a lettered appendix heading on its own line, e.g. "A Proofs of Section 3"
_APPENDIX_HEADING_RE = re.compile(r"(?m)^[A-Z]\s+[A-Z][^\n]{0,80}$")
_APA_START_RE = re.compile(r"(?m)^(?=[A-Z][^\n]{0,150}?\((?:1[89]\d{2}|20\d{2})[a-z]?\))")

_DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;]+)", re.IGNORECASE)
_QUOTED_TITLE_RE = re.compile(r"[\"“]([^\"”]{10,})[\"”]")
_APA_YEAR_RE = re.compile(r"\((1[89]\d{2}|20\d{2})[a-z]?\)\.?\s*")
# LNCS/Springer: "Abdar, M., Pourpanah, F., et al.: Title. Venue 76, 243-297 (2021)"
_LNCS_RE = re.compile(r"^(?P<authors>[^:]{5,300}?,\s*[A-Z]\.[^:]*?):\s+(?P<rest>.+)$")
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


def _sequential_slices(section: str, markers: list[re.Match[str]]) -> list[str]:
    """Slice at numbered markers, stopping when numbering breaks.

    Reference markers run 1, 2, 3, ...; the first out-of-sequence number is a
    citation in trailing appendix text, so everything from there on is dropped.
    """
    starts: list[int] = []
    end = len(section)
    expected: int | None = None
    for marker in markers:
        number = int(marker.group(1))
        if expected is not None and number != expected:
            end = marker.start()
            break
        starts.append(marker.start())
        expected = number + 1
    chunks = [section[a:b] for a, b in zip(starts, starts[1:] + [end], strict=True)]
    if chunks:
        # the last reference has no following marker to end it, so appendix text
        # bleeds in; cut at the first appendix-style heading line
        heading = _APPENDIX_HEADING_RE.search(chunks[-1])
        if heading and heading.start() > 0:
            chunks[-1] = chunks[-1][: heading.start()]
    return chunks


def split_references(section: str) -> list[str]:
    """Split a references section into individual raw reference strings."""
    markers = list(_BRACKET_MARKER_RE.finditer(section))
    if len(markers) >= 2:  # IEEE/LNCS style: [1] ... [2] ...
        chunks = _sequential_slices(section, markers)
    elif len(list(_NUMBER_MARKER_RE.finditer(section))) >= 2:  # "1. ..." style
        chunks = _sequential_slices(section, list(_NUMBER_MARKER_RE.finditer(section)))
    elif "\n\n" in section:  # blank-line separated
        chunks = re.split(r"\n\s*\n", section)
    else:  # APA-ish: new entry starts with "Author, A. ... (year)"
        marks = [m.start() for m in _APA_START_RE.finditer(section)]
        chunks = _slice_at(section, marks) if len(marks) >= 2 else [section]
    cleaned = [clean_text(c[:_MAX_CHUNK_CHARS].replace("\n", " ")) for c in chunks]
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
    # "(year)" only splits authors from title when text follows it; a "(year)" at the
    # very end is the LNCS/Springer convention instead.
    apa_mid = apa is not None and apa.end() < len(stripped) - 1
    quoted = _QUOTED_TITLE_RE.search(stripped)
    lncs = _LNCS_RE.match(stripped)
    if quoted:  # "Title in quotes" style
        title = quoted.group(1).strip(" .,")
        authors = _parse_authors(stripped[: quoted.start()])
        venue = stripped[quoted.end() :].strip(" .,") or None
    elif apa_mid and apa is not None:  # Author, A. (2016). Title. Venue.
        authors = _parse_authors(stripped[: apa.start()])
        rest = stripped[apa.end() :]
        segments = _SEGMENT_SPLIT_RE.split(rest)
        title = segments[0].strip(" .,") if segments else None
        venue = segments[1].strip(" .,") if len(segments) > 1 else None
    elif lncs:  # Author, A., Author, B.: Title. Venue 76, 1-10 (2021)
        authors = _parse_authors(lncs.group("authors"))
        segments = _SEGMENT_SPLIT_RE.split(lncs.group("rest"))
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

    if not title or not 5 <= len(title) <= 300:
        return None
    if venue:
        venue = re.sub(r"^(?:in|In):?\s+", "", venue)
        venue = re.sub(r"[,\s]*(?:1[89]\d{2}|20\d{2}).*$", "", venue).strip(" (,.")
        # drop trailing volume/page numbers: "Information fusion 76, 243-297" -> name only
        venue = re.sub(r"(?:[\s,]*\d+(?:\s*[–—-]\s*\d+)?)+\s*$", "", venue)
        venue = re.sub(r"[,\s]*(?:pp?|vol|no)\.?\s*$", "", venue).strip(" (,.") or None

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
