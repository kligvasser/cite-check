from pathlib import Path

import pytest
from rapidfuzz import fuzz

from cite_check.models import ScholarRecord
from cite_check.normalize import comparison_key

FIXTURES = Path(__file__).parent / "fixtures"


def record(title, authors, year, venue):
    return ScholarRecord(title=title, authors=authors, year=year, venue=venue, backend="fake")


# The fake "Google Scholar index": ground-truth records for the corpus papers.
SCHOLAR_INDEX = [
    record(
        "Attention is All You Need",
        ["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"],
        2017,
        "Advances in Neural Information Processing Systems",
    ),
    record(
        "Deep Residual Learning for Image Recognition",
        ["Kaiming He", "Xiangyu Zhang", "Shaoqing Ren", "Jian Sun"],
        2016,
        "Proceedings of the IEEE Conference on Computer Vision and Pattern Recognition",
    ),
    record(
        "Generative Adversarial Nets",
        ["Ian Goodfellow", "Jean Pouget-Abadie", "Yoshua Bengio"],
        2014,
        "Advances in Neural Information Processing Systems",
    ),
    record(
        "BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
        ["Jacob Devlin", "Ming-Wei Chang", "Kenton Lee", "Kristina Toutanova"],
        2019,
        "NAACL",
    ),
    record(
        "Adam: A Method for Stochastic Optimization",
        ["Diederik P. Kingma", "Jimmy Ba"],
        2015,
        "ICLR",
    ),
]


class FakeBackend:
    """In-memory ScholarBackend: fuzzy title search over a fixed index."""

    name = "fake"

    def __init__(self, index=SCHOLAR_INDEX):
        self.index = index
        self.calls = 0

    def search(self, query, limit=5):
        self.calls += 1
        q = comparison_key(query)
        ranked = sorted(
            self.index,
            key=lambda r: fuzz.token_set_ratio(q, comparison_key(r.title)),
            reverse=True,
        )
        return ranked[:limit]


@pytest.fixture
def fake_backend():
    return FakeBackend()
