from cite_check.matching import (
    TITLE_CANDIDATE,
    TITLE_DID_YOU_MEAN,
    author_score,
    classify,
    score_candidate,
    title_score,
    year_score,
)
from cite_check.models import Reference, ScholarRecord, VerificationStatus


def make_ref(**kwargs):
    defaults = dict(
        key="k",
        raw="@article{k, ...}",
        title="Attention is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        year=2017,
        venue="NeurIPS",
        source="bibtex",
    )
    defaults.update(kwargs)
    return Reference(**defaults)


def make_record(**kwargs):
    defaults = dict(
        title="Attention is All You Need",
        authors=["Ashish Vaswani", "Noam Shazeer"],
        year=2017,
        venue="NeurIPS",
        backend="fake",
    )
    defaults.update(kwargs)
    return ScholarRecord(**defaults)


def test_exact_match_is_verified():
    result = classify(make_ref(), [make_record()])
    assert result.status == VerificationStatus.VERIFIED
    assert result.score >= 90
    assert result.field_diffs == {}


def test_year_off_by_one_still_verified():
    result = classify(make_ref(year=2018), [make_record()])
    assert result.status == VerificationStatus.VERIFIED


def test_wrong_year_is_mismatch():
    result = classify(make_ref(year=2015), [make_record()])
    assert result.status == VerificationStatus.MISMATCH
    assert "year" in result.field_diffs
    assert result.field_diffs["year"] == ("2015", "2017")


def test_wrong_authors_is_mismatch():
    result = classify(make_ref(authors=["John Smith", "Mary Jones"]), [make_record()])
    assert result.status == VerificationStatus.MISMATCH
    assert "authors" in result.field_diffs


def test_no_candidates_is_not_found():
    result = classify(make_ref(), [])
    assert result.status == VerificationStatus.NOT_FOUND
    assert result.best_match is None


def test_unrelated_candidate_is_not_found():
    result = classify(make_ref(), [make_record(title="Soil Composition of the Andes")])
    assert result.status == VerificationStatus.NOT_FOUND


def test_did_you_mean_range_produces_note():
    cited = "A survey of deep learning methods"
    found = "A survey of deep learning methods for natural language processing"
    score = title_score(cited, found)
    assert TITLE_DID_YOU_MEAN <= score < TITLE_CANDIDATE, f"fixture drifted: {score}"
    result = classify(
        make_ref(title=cited, authors=[], year=None, venue=None),
        [make_record(title=found, authors=[], year=None, venue=None)],
    )
    assert result.status == VerificationStatus.NOT_FOUND
    assert result.note is not None and "Closest match" in result.note


def test_author_score_handles_initials():
    assert author_score(["Ashish Vaswani"], ["A Vaswani"]) == 100.0


def test_author_score_last_first_forms():
    assert author_score(["Kaiming He"], ["He, Kaiming"]) == 100.0


def test_author_score_missing_side_is_none():
    assert author_score([], ["A Vaswani"]) is None


def test_year_score_soft_matching():
    assert year_score(2017, 2017) == 100.0
    assert year_score(2017, 2018) == 70.0
    assert year_score(2017, 2019) == 0.0
    assert year_score(None, 2017) is None


def test_missing_fields_redistribute_weights():
    ref = make_ref(authors=[], year=None, venue=None)
    score = score_candidate(ref, make_record())
    assert score.overall == 100.0  # only title available, perfect match
