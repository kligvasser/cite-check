from cite_check.normalize import (
    clean_text,
    comparison_key,
    extract_year,
    normalize_author,
    split_bibtex_authors,
)


def test_clean_text_unescapes_latex():
    assert clean_text(r"Schmidhuber, J{\"u}rgen") == "Schmidhuber, Jürgen"


def test_clean_text_collapses_whitespace():
    assert clean_text("  a\n b\t c ") == "a b c"


def test_comparison_key_strips_punctuation_and_case():
    assert comparison_key("Attention is All You Need!") == "attention is all you need"


def test_normalize_author_last_first():
    assert normalize_author("He, Kaiming") == "Kaiming He"


def test_normalize_author_already_first_last():
    assert normalize_author("Kaiming He") == "Kaiming He"


def test_split_bibtex_authors():
    assert split_bibtex_authors("He, Kaiming and Zhang, Xiangyu") == [
        "Kaiming He",
        "Xiangyu Zhang",
    ]


def test_extract_year():
    assert extract_year("2016") == 2016
    assert extract_year("c. 2016, revised") == 2016
    assert extract_year("no year here") is None
    assert extract_year("300") is None
