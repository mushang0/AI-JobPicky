from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MatchingConfig:
    """Versioned knobs for candidate fusion (architecture §4.8)."""

    keyword_weight: float = 0.5
    semantic_weight: float = 0.5
    max_candidates: int = 50
    min_retrieval_score: float = 0.0
    # One version covers the embedding, evaluator, prompt/schema, and fusion
    # choices used by the recommendation pipeline.
    version: str = "recommendation-v1"

    def __post_init__(self) -> None:
        if self.keyword_weight < 0 or self.semantic_weight < 0:
            raise ValueError("retrieval weights must be non-negative")
        if abs(self.keyword_weight + self.semantic_weight - 1.0) > 1e-9:
            raise ValueError("retrieval weights must sum to 1.0")
        if self.max_candidates < 1:
            raise ValueError("max_candidates must be at least 1")
        if not 0.0 <= self.min_retrieval_score <= 1.0:
            raise ValueError("min_retrieval_score must be within 0.0 to 1.0")
