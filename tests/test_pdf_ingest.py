from pathlib import Path

import pytest

from cite_check.ingest.pdf import (
    find_references_section,
    parse_pdf,
    parse_pdf_text,
    split_references,
)

FIXTURES = Path(__file__).parent / "fixtures"
IEEE_TEXT = (FIXTURES / "ieee_refs.txt").read_text()
APA_TEXT = (FIXTURES / "apa_refs.txt").read_text()
LNCS_TEXT = (FIXTURES / "lncs_refs.txt").read_text()


def test_find_references_section_cuts_body_and_appendix():
    section = find_references_section(IEEE_TEXT)
    assert "Conclusion" not in section
    assert "Appendix" not in section
    assert "[1]" in section and "[3]" in section


def test_missing_section_raises():
    with pytest.raises(ValueError, match="No references"):
        find_references_section("just some text without a bibliography heading")


def test_split_ieee_numbered():
    refs = split_references(find_references_section(IEEE_TEXT))
    assert len(refs) == 3
    assert refs[0].startswith("[1]")


def test_parse_ieee_quoted_titles():
    refs = parse_pdf_text(IEEE_TEXT)
    assert len(refs) == 3
    attention, resnet, bert = refs
    assert attention.title == "Attention is all you need"
    assert attention.year == 2017
    assert any("Vaswani" in a for a in attention.authors)
    assert resnet.title == "Deep residual learning for image recognition"
    assert resnet.venue == "Proc. IEEE CVPR"
    assert bert.doi == "10.18653/v1/N19-1423"
    assert all(r.source == "pdf" for r in refs)
    assert all(r.raw for r in refs)  # raw always preserved for manual inspection


def test_parse_apa_author_year():
    refs = parse_pdf_text(APA_TEXT)
    assert len(refs) == 2
    gan, adam = refs
    assert gan.title == "Generative adversarial nets"
    assert gan.year == 2014
    assert any("Goodfellow" in a for a in gan.authors)
    assert adam.title == "Adam: A method for stochastic optimization"
    assert adam.year == 2015


def test_parse_lncs_springer_style():
    refs = parse_pdf_text(LNCS_TEXT)
    assert len(refs) == 3  # appendix text after the numbering break is dropped
    review, hallucinations, tradeoff = refs
    assert review.title == (
        "A review of uncertainty quantification in deep learning: "
        "Techniques, applications and challenges"
    )
    assert review.venue == "Information fusion"
    assert review.year == 2021
    assert any("Abdar" in a for a in review.authors)
    assert hallucinations.title == (
        "Looks too good to be true: An information-theoretic analysis "
        "of hallucinations in generative restoration models"
    )
    assert hallucinations.year == 2024
    assert tradeoff.title == "The perception-distortion tradeoff"
    assert (
        tradeoff.venue
        == "Proceedings of the IEEE conference on computer vision and pattern recognition"
    )


def test_arxiv_id_is_not_mistaken_for_year():
    from cite_check.ingest.pdf import parse_reference_string

    ref = parse_reference_string(
        "[7] A. Author, B. Author. A method for something quite specific. "
        "arXiv preprint arXiv:2010.12345, 2022.",
        7,
    )
    assert ref is not None
    assert ref.year == 2022  # not 2010 from the arXiv id
    assert ref.venue == "arXiv preprint"  # id stripped from the venue


def test_generic_ref_with_colon_title_is_not_lncs():
    from cite_check.ingest.pdf import parse_reference_string

    ref = parse_reference_string(
        "[3] J. Doe, K. Smith. BERT: pretraining of transformers for language. NAACL, 2019.",
        3,
    )
    assert ref is not None
    assert ref.title == "BERT: pretraining of transformers for language"
    assert ref.year == 2019


def test_parse_real_pdf_end_to_end(tmp_path):
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "paper.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_textbox(fitz.Rect(36, 36, 559, 806), IEEE_TEXT, fontsize=9)
    doc.save(pdf_path)
    doc.close()

    refs = parse_pdf(pdf_path)
    assert len(refs) == 3
    assert refs[0].title == "Attention is all you need"
