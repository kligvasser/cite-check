from pathlib import Path

from cite_check.ingest import parse_bibtex
from cite_check.normalize import dedupe_references

FIXTURE = Path(__file__).parent / "fixtures" / "sample.bib"


def test_parses_entries_and_skips_titleless():
    refs = parse_bibtex(FIXTURE)
    # 5 entries in fixture, one has no title
    assert len(refs) == 4
    assert all(r.source == "bibtex" for r in refs)


def test_fields_mapped():
    refs = {r.key: r for r in parse_bibtex(FIXTURE)}
    resnet = refs["he2016resnet"]
    assert resnet.title == "Deep Residual Learning for Image Recognition"
    assert resnet.authors[0] == "Kaiming He"
    assert len(resnet.authors) == 4
    assert resnet.year == 2016
    assert resnet.doi == "10.1109/CVPR.2016.90"
    assert "Computer Vision" in (resnet.venue or "")


def test_latex_escapes_cleaned():
    refs = {r.key: r for r in parse_bibtex(FIXTURE)}
    entry = refs["schmidhuber2015latex"]
    assert entry.authors == ["Jürgen Schmidhuber"]
    assert "ümlauts" in entry.title
    assert "{" not in entry.title


def test_raw_block_preserved():
    refs = {r.key: r for r in parse_bibtex(FIXTURE)}
    assert "vaswani2017attention" in refs["vaswani2017attention"].raw


def test_dedupe_by_title_and_year():
    refs = dedupe_references(parse_bibtex(FIXTURE))
    # vaswani2017attention and dupe2017attention collide on (title, year)
    assert len(refs) == 3
    keys = {r.key for r in refs}
    assert "dupe2017attention" not in keys
