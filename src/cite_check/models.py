"""Core data models shared across the pipeline (plan §3.1)."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field


class Reference(BaseModel):
    """A single bibliographic reference extracted from the input."""

    key: str | None = None  # BibTeX key or generated id (e.g. "ref-17")
    raw: str  # original raw string (PDF) or raw BibTeX block
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None  # journal / conference / publisher
    doi: str | None = None
    arxiv_id: str | None = None  # e.g. "2207.12598" (no version suffix)
    url: str | None = None  # web resources (blogs, model cards) cited via url/howpublished
    entry_type: str | None = None  # BibTeX entry type, lowercased ("misc", "article", ...)
    source: Literal["bibtex", "pdf"]


class ScholarRecord(BaseModel):
    """A candidate record returned by a verification backend."""

    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    cited_by: int | None = None
    backend: str
    # preprint records carry the *first posting* year: a later cited year is expected
    preprint: bool = False


class VerificationStatus(StrEnum):
    VERIFIED = "VERIFIED"
    MISMATCH = "MISMATCH"
    NOT_FOUND = "NOT_FOUND"
    WEB_ONLY = "WEB_ONLY"  # not a scholarly record (blog, model card) but its URL is live
    ERROR = "ERROR"


# statuses that do not fail the run (exit code 0)
PASSING_STATUSES = frozenset({VerificationStatus.VERIFIED, VerificationStatus.WEB_ONLY})


class SuggestedFix(BaseModel):
    corrected_fields: dict[str, str]
    corrected_bibtex: str | None = None
    note: str


class VerificationResult(BaseModel):
    reference: Reference
    status: VerificationStatus
    best_match: ScholarRecord | None = None
    score: float = 0.0  # overall 0-100 confidence
    # field -> (cited value, scholar value)
    field_diffs: dict[str, tuple[str, str]] = Field(default_factory=dict)
    suggested_fix: SuggestedFix | None = None
    note: str | None = None  # e.g. "did you mean ...?" or backend error detail
