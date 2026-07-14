"""Verification backends: Google Scholar (primary) + corroborating APIs (plan §2)."""

from cite_check.backends.base import BackendError, CachedBackend, ScholarBackend
from cite_check.backends.crossref import CrossrefBackend
from cite_check.backends.scholarly_backend import ScholarlyBackend
from cite_check.backends.semantic_scholar import SemanticScholarBackend
from cite_check.backends.serpapi import SerpApiBackend

__all__ = [
    "BackendError",
    "CachedBackend",
    "CrossrefBackend",
    "ScholarBackend",
    "ScholarlyBackend",
    "SemanticScholarBackend",
    "SerpApiBackend",
]
