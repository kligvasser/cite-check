"""Verification engine: query strategy + classification + fix building (plan §4.3)."""

from collections.abc import Callable

from cite_check.backends.base import BackendError, ScholarBackend
from cite_check.backends.crossref import CrossrefBackend
from cite_check.fixes import build_fix
from cite_check.matching import TITLE_CANDIDATE, classify, title_score
from cite_check.models import Reference, VerificationResult, VerificationStatus


class VerificationEngine:
    def __init__(
        self,
        backend: ScholarBackend,
        crossref: CrossrefBackend | None = None,
        corroborator: ScholarBackend | None = None,
        results_per_query: int = 5,
    ) -> None:
        self._backend = backend
        self._crossref = crossref
        self._corroborator = corroborator
        self._limit = results_per_query

    def _refine_query(self, ref: Reference) -> str | None:
        parts = [ref.title]
        if ref.authors:
            parts.append(ref.authors[0].split()[-1])  # first author's last name
        if ref.year:
            parts.append(str(ref.year))
        return " ".join(parts) if len(parts) > 1 else None

    def verify_one(self, ref: Reference) -> VerificationResult:
        candidates = []

        # a) DOI present -> resolve directly (cheap, exact)
        if ref.doi and self._crossref is not None:
            try:
                record = self._crossref.by_doi(ref.doi)
                if record is not None:
                    candidates.append(record)
            except BackendError:
                pass  # DOI resolution is a shortcut, not a requirement

        # b) quoted-title query; c) refined query if the best title match is weak
        try:
            quoted_title = ref.title.replace('"', "")  # embedded quotes break the phrase query
            candidates += self._backend.search(f'"{quoted_title}"', self._limit)
            best_title = max((title_score(ref.title, c.title) for c in candidates), default=0.0)
            if best_title < TITLE_CANDIDATE:
                refined = self._refine_query(ref)
                if refined:
                    candidates += self._backend.search(refined, self._limit)
        except BackendError as exc:
            if not candidates:
                return VerificationResult(
                    reference=ref, status=VerificationStatus.ERROR, note=str(exc)
                )

        result = classify(ref, candidates)
        if result.status == VerificationStatus.MISMATCH and result.best_match is not None:
            result.suggested_fix = build_fix(ref, result.best_match, result.field_diffs)
            self._corroborate(result)
        return result

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
