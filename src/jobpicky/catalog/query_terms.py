from __future__ import annotations

import re

from ..contracts import JobFact

# Contiguous CJK runs (Chinese phrases) or latin/digit words (skills like
# Python, C++, k8s). Query text from the matching baseline is newline-joined
# roles, skills, experience summary and extra request, so punctuation and
# whitespace are natural term boundaries.
_TERM_RE = re.compile(r"[一-鿿]+|[A-Za-z0-9+#.]+")


def extract_terms(query_text: str) -> list[str]:
    """Split query text into deduplicated search terms, order preserved.

    Single-character terms are dropped: they hit almost everything and carry
    no signal. Longer CJK phrases are kept as-is — they may rarely hit, but
    deterministic segmentation is evaluation-set work (plan 003, decision 4).
    """
    terms: list[str] = []
    seen: set[str] = set()
    for match in _TERM_RE.finditer(query_text):
        term = match.group(0).lower()
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        terms.append(term)
    return terms


def term_hit_score(terms: list[str], job: JobFact) -> float:
    """Fraction of terms found in the job's title, company or description."""
    if not terms:
        return 0.0
    haystack = " ".join([job.title, job.company_name, job.description or ""]).lower()
    hits = sum(1 for term in terms if term in haystack)
    return hits / len(terms)


__all__ = ["extract_terms", "term_hit_score"]
