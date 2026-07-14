"""Normalization helpers: LaTeX unescaping, unicode, author names (plan §4.2)."""

import re
import unicodedata

from pylatexenc.latex2text import LatexNodes2Text

from cite_check.models import Reference

_latex = LatexNodes2Text()

_WHITESPACE_RE = re.compile(r"\s+")
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def clean_text(value: str) -> str:
    """Convert LaTeX escapes to unicode, normalize, and collapse whitespace."""
    text = _latex.latex_to_text(value)
    text = unicodedata.normalize("NFKC", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def comparison_key(value: str) -> str:
    """Lowercased, punctuation-free form used for fuzzy comparison."""
    text = clean_text(value).lower()
    text = re.sub(r"[^\w\s]", " ", text)
    return _WHITESPACE_RE.sub(" ", text).strip()


def normalize_author(name: str) -> str:
    """Return an author name as ``First Last`` regardless of input form."""
    name = clean_text(name)
    if "," in name:
        last, _, first = name.partition(",")
        name = f"{first.strip()} {last.strip()}".strip()
    return _WHITESPACE_RE.sub(" ", name).strip()


def split_bibtex_authors(field: str) -> list[str]:
    """Split a BibTeX author field on ``and`` and normalize each name."""
    parts = re.split(r"\s+and\s+", field.strip())
    return [normalize_author(p) for p in parts if p.strip()]


def extract_year(value: str) -> int | None:
    """Pull a plausible publication year out of a free-form string."""
    match = _YEAR_RE.search(value)
    return int(match.group()) if match else None


def dedupe_references(refs: list[Reference]) -> list[Reference]:
    """Drop references whose (title, year) comparison keys collide."""
    seen: set[tuple[str, int | None]] = set()
    unique: list[Reference] = []
    for ref in refs:
        key = (comparison_key(ref.title), ref.year)
        if key not in seen:
            seen.add(key)
            unique.append(ref)
    return unique
