"""Verification engine: query strategy + classification + fix building (plan §4.3)."""

import contextlib
from collections.abc import Callable, Sequence

from cite_check.backends.arxiv import ArxivBackend
from cite_check.backends.base import BackendError, ScholarBackend
from cite_check.backends.crossref import CrossrefBackend
from cite_check.fixes import build_fix
from cite_check.matching import TITLE_CANDIDATE, classify, title_score
from cite_check.models import Reference, ScholarRecord, VerificationResult, VerificationStatus

# entry types that may legitimately cite a non-indexed web resource
WEB_ENTRY_TYPES = frozenset({"misc", "online", "electronic", "www", "manual", "techreport"})


class VerificationEngine:
    def __init__(
        self,
        backend: ScholarBackend | None,
        crossref: CrossrefBackend | None = None,
        corroborator: ScholarBackend | None = None,
        results_per_query: int = 5,
        arxiv: ArxivBackend | None = None,
        fallbacks: Sequence[ScholarBackend] = (),
        url_checker: Callable[[str], int | None] | None = None,
    ) -> None:
        """
        backend: primary index (Google Scholar); None if it is known to be unavailable.
        arxiv: resolves cited arXiv ids (and catches ids that point to another paper).
        fallbacks: title searches tried, in order, when the primary finds no match.
        url_checker: returns the HTTP status of a URL; enables the WEB_ONLY status.
        """
        self._backend = backend
        self._crossref = crossref
        self._corroborator = corroborator
        self._limit = results_per_query
        self._arxiv = arxiv
        self._fallbacks = list(fallbacks)
        self._url_checker = url_checker

    def _refine_query(self, ref: Reference) -> str | None:
        parts = [ref.title]
        if ref.authors:
            parts.append(ref.authors[0].split()[-1])  # first author's last name
        if ref.year:
            parts.append(str(ref.year))
        return " ".join(parts) if len(parts) > 1 else None

    def _resolve_identifiers(
        self, ref: Reference
    ) -> tuple[list[ScholarRecord], dict[str, tuple[str, str]]]:
        """Look up the cited DOI / arXiv id; return found records + identifier diffs.

        An identifier that resolves to a *different* paper is a classic corruption
        (copy-pasted entry, LLM-hallucinated DOI) that title search alone never sees.
        """
        records: list[ScholarRecord] = []
        diffs: dict[str, tuple[str, str]] = {}

        def check(field: str, value: str, record: ScholarRecord | None) -> None:
            if record is None:
                return
            records.append(record)
            if title_score(ref.title, record.title) < TITLE_CANDIDATE:
                diffs[field] = (value, f'resolves to a different paper: "{record.title}"')

        if ref.doi and self._crossref is not None:
            # a shortcut, not a requirement; a Crossref 404 is no evidence of a bad DOI
            # either (DataCite DOIs, e.g. arXiv's 10.48550, live elsewhere)
            with contextlib.suppress(BackendError):
                check("doi", ref.doi, self._crossref.by_doi(ref.doi))
        if ref.arxiv_id and self._arxiv is not None:
            try:
                record = self._arxiv.by_id(ref.arxiv_id)
                if record is None:
                    diffs["arxiv"] = (ref.arxiv_id, "no such arXiv id")
                check("arxiv", ref.arxiv_id, record)
            except BackendError:
                pass
        return records, diffs

    @staticmethod
    def _best_title(ref: Reference, candidates: list[ScholarRecord]) -> float:
        return max((title_score(ref.title, c.title) for c in candidates), default=0.0)

    def _search(self, ref: Reference, candidates: list[ScholarRecord]) -> str | None:
        """Extend ``candidates`` from the primary then fallbacks; return the last error."""
        error: str | None = None
        if self._backend is not None:
            # b) quoted-title query; c) refined query if the best title match is weak
            try:
                quoted_title = ref.title.replace('"', "")  # embedded quotes break the phrase
                candidates += self._backend.search(f'"{quoted_title}"', self._limit)
                if self._best_title(ref, candidates) < TITLE_CANDIDATE:
                    refined = self._refine_query(ref)
                    if refined:
                        candidates += self._backend.search(refined, self._limit)
            except BackendError as exc:
                error = str(exc)
        # d) fallbacks only while nothing plausible has been found
        for fallback in self._fallbacks:
            if self._best_title(ref, candidates) >= TITLE_CANDIDATE:
                break
            try:
                candidates += fallback.search(ref.title, self._limit)
            except BackendError as exc:
                error = str(exc)
        return error

    def verify_one(self, ref: Reference) -> VerificationResult:
        candidates, id_diffs = self._resolve_identifiers(ref)
        error = self._search(ref, candidates)
        if error and not candidates:
            return VerificationResult(reference=ref, status=VerificationStatus.ERROR, note=error)

        result = classify(ref, candidates)
        if id_diffs:
            result.field_diffs.update(id_diffs)
            if result.status == VerificationStatus.VERIFIED:
                result.status = VerificationStatus.MISMATCH
        if result.status == VerificationStatus.NOT_FOUND:
            self._check_web_resource(result)
        if result.status == VerificationStatus.MISMATCH and result.best_match is not None:
            result.suggested_fix = build_fix(ref, result.best_match, result.field_diffs)
            self._corroborate(result)
        return result

    def _check_web_resource(self, result: VerificationResult) -> None:
        """A blog post / model card is legitimately absent from scholarly indexes."""
        ref = result.reference
        if self._url_checker is None or ref.entry_type not in WEB_ENTRY_TYPES:
            return
        if not ref.url:
            result.note = "Web resource with no URL — add a url field so it can be checked."
            return
        status = self._url_checker(ref.url)
        if status is not None and status < 400:
            result.status = VerificationStatus.WEB_ONLY
            result.best_match, result.score = None, 0.0  # a "closest paper" is noise here
            result.note = f"Not a scholarly record; URL is live (HTTP {status}). Check by hand."
        else:
            result.note = f"URL unreachable ({'HTTP ' + str(status) if status else 'no response'})."

    def _corroborate(self, result: VerificationResult) -> None:
        """Cross-check a mismatch's found record against a secondary source (plan §8)."""
        if self._corroborator is None or result.best_match is None:
            return
        try:
            others = self._corroborator.search(result.best_match.title, 3)
        except BackendError:
            return
        for other in others:
            if (
                title_score(result.best_match.title, other.title) >= TITLE_CANDIDATE
                and other.year == result.best_match.year
            ):
                result.note = f"Correction corroborated by {other.backend}."
                return
        result.note = "Correction NOT corroborated by a secondary source — double-check it."

    def verify_all(
        self,
        refs: list[Reference],
        on_result: Callable[[VerificationResult], None] | None = None,
    ) -> list[VerificationResult]:
        results = []
        for ref in refs:
            result = self.verify_one_safe(ref)
            results.append(result)
            if on_result is not None:
                on_result(result)
        return results

    def verify_one_safe(self, ref: Reference) -> VerificationResult:
        """verify_one, but one bad reference must not kill the whole run."""
        try:
            return self.verify_one(ref)
        except Exception as exc:
            return VerificationResult(
                reference=ref,
                status=VerificationStatus.ERROR,
                note=f"unexpected error: {exc}",
            )
