"""Candidate scoring and classification (plan §4.3).

Weights and floors are module constants so they stay tunable in one place.
Venue gets scoring weight but no floor: venues are abbreviated too inconsistently
("CVPR" vs "Proceedings of the IEEE Conference on...") to flag as a mismatch.
"""

from dataclasses import dataclass

from rapidfuzz import fuzz

from cite_check.models import (
    Reference,
    ScholarRecord,
    VerificationResult,
    VerificationStatus,
)
from cite_check.normalize import comparison_key, normalize_author

WEIGHTS = {"title": 0.55, "authors": 0.25, "year": 0.15, "venue": 0.05}
FLOORS = {"title": 90.0, "authors": 75.0, "year": 70.0}

VERIFY_OVERALL = 90.0  # overall score needed for VERIFIED
TITLE_CANDIDATE = 85.0  # title score needed to even consider a candidate "the same paper"
TITLE_DID_YOU_MEAN = 60.0  # below CANDIDATE but above this -> "did you mean ...?"


@dataclass
class MatchScore:
    title: float
    authors: float | None  # None when either side lacks the field
    year: float | None
    venue: float | None
    overall: float


def title_score(cited: str, found: str) -> float:
    return fuzz.token_sort_ratio(comparison_key(cited), comparison_key(found))


def _author_parts(name: str) -> tuple[str, str]:
    """Return (last name, first initial) for a normalized name."""
    tokens = normalize_author(name).split()
    last = tokens[-1].lower() if tokens else ""
    initial = tokens[0][0].lower() if len(tokens) > 1 else ""
    return last, initial


def author_score(cited: list[str], found: list[str]) -> float | None:
    """Fraction of cited authors present in the found list (last name + initial)."""
    if not cited or not found:
        return None
    found_parts = [_author_parts(name) for name in found]
    matched = 0
    for name in cited:
        last, initial = _author_parts(name)
        for f_last, f_initial in found_parts:
            if fuzz.ratio(last, f_last) >= 85 and (
                not initial or not f_initial or initial == f_initial
            ):
                matched += 1
                break
    return 100.0 * matched / len(cited)


def year_score(cited: int | None, found: int | None) -> float | None:
    if cited is None or found is None:
        return None
    if cited == found:
        return 100.0
    if abs(cited - found) == 1:  # Scholar years are noisy: preprint vs published
        return 70.0
    return 0.0


def venue_score(cited: str | None, found: str | None) -> float | None:
    if not cited or not found:
        return None
    return fuzz.partial_ratio(comparison_key(cited), comparison_key(found))


def score_candidate(ref: Reference, record: ScholarRecord) -> MatchScore:
    scores: dict[str, float | None] = {
        "title": title_score(ref.title, record.title),
        "authors": author_score(ref.authors, record.authors),
        "year": year_score(ref.year, record.year),
        "venue": venue_score(ref.venue, record.venue),
    }
    available = {k: v for k, v in scores.items() if v is not None}
    total_weight = sum(WEIGHTS[k] for k in available)
    overall = sum(WEIGHTS[k] * v for k, v in available.items()) / total_weight
    return MatchScore(
        title=scores["title"],  # type: ignore[arg-type]
        authors=scores["authors"],
        year=scores["year"],
        venue=scores["venue"],
        overall=overall,
    )


def _field_diffs(
    ref: Reference, record: ScholarRecord, score: MatchScore
) -> dict[str, tuple[str, str]]:
    diffs: dict[str, tuple[str, str]] = {}
    if score.title < FLOORS["title"]:
        diffs["title"] = (ref.title, record.title)
    if score.authors is not None and score.authors < FLOORS["authors"]:
        diffs["authors"] = ("; ".join(ref.authors), "; ".join(record.authors))
    if score.year is not None and score.year < FLOORS["year"]:
        diffs["year"] = (str(ref.year), str(record.year))
    return diffs


def classify(ref: Reference, candidates: list[ScholarRecord]) -> VerificationResult:
    """Pick the best candidate and classify the reference (fix built separately)."""
    if not candidates:
        return VerificationResult(reference=ref, status=VerificationStatus.NOT_FOUND)

    scored = [(record, score_candidate(ref, record)) for record in candidates]
    record, score = max(scored, key=lambda pair: pair[1].overall)

    if score.title >= TITLE_CANDIDATE:
        diffs = _field_diffs(ref, record, score)
        if not diffs and score.overall >= VERIFY_OVERALL:
            status = VerificationStatus.VERIFIED
        else:
            status = VerificationStatus.MISMATCH
        return VerificationResult(
            reference=ref,
            status=status,
            best_match=record,
            score=round(score.overall, 1),
            field_diffs=diffs,
        )

    if score.title >= TITLE_DID_YOU_MEAN:
        return VerificationResult(
            reference=ref,
            status=VerificationStatus.NOT_FOUND,
            best_match=record,
            score=round(score.overall, 1),
            note=f'Closest match (not close enough to verify): "{record.title}"',
        )

    return VerificationResult(reference=ref, status=VerificationStatus.NOT_FOUND)
