import pytest

from jobpicky.contracts import RetrievalChannel
from jobpicky.matching import BaselineMatchingService, MatchingConfig
from matching.factories import make_hit

KEYWORD = RetrievalChannel.KEYWORD
SEMANTIC = RetrievalChannel.SEMANTIC


def test_dual_channel_hit_merges_into_single_candidate() -> None:
    service = BaselineMatchingService()

    candidates = service.merge_candidates(
        [make_hit("job-1", 0.8, KEYWORD)],
        [make_hit("job-1", 0.6, SEMANTIC)],
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.job_id == "job-1"
    assert candidate.keyword_score == 0.8
    assert candidate.semantic_score == 0.6
    assert candidate.retrieval_score == pytest.approx(0.5 * 0.8 + 0.5 * 0.6)
    assert candidate.sources == [KEYWORD, SEMANTIC]


def test_single_channel_hit_keeps_single_source() -> None:
    candidates = BaselineMatchingService().merge_candidates(
        [make_hit("job-1", 0.8, KEYWORD)],
        [make_hit("job-2", 0.6, SEMANTIC)],
    )

    by_id = {candidate.job_id: candidate for candidate in candidates}
    assert by_id["job-1"].sources == [KEYWORD]
    assert by_id["job-1"].semantic_score is None
    assert by_id["job-1"].retrieval_score == pytest.approx(0.5 * 0.8)
    assert by_id["job-2"].sources == [SEMANTIC]
    assert by_id["job-2"].keyword_score is None


def test_merge_is_reproducible_regardless_of_input_order() -> None:
    service = BaselineMatchingService()
    keyword_hits = [make_hit("job-1", 0.9, KEYWORD), make_hit("job-2", 0.7, KEYWORD)]
    semantic_hits = [make_hit("job-2", 0.8, SEMANTIC), make_hit("job-3", 0.6, SEMANTIC)]

    first = service.merge_candidates(keyword_hits, semantic_hits)
    second = service.merge_candidates(list(reversed(keyword_hits)), list(reversed(semantic_hits)))

    assert first == second
    assert [candidate.job_id for candidate in first] == ["job-2", "job-1", "job-3"]


def test_equal_scores_fall_back_to_job_id_order() -> None:
    candidates = BaselineMatchingService().merge_candidates(
        [make_hit("job-b", 0.5, KEYWORD), make_hit("job-a", 0.5, KEYWORD)],
        [],
    )

    assert [candidate.job_id for candidate in candidates] == ["job-a", "job-b"]


def test_custom_weights_change_fused_score() -> None:
    service = BaselineMatchingService(MatchingConfig(keyword_weight=0.8, semantic_weight=0.2))

    candidates = service.merge_candidates(
        [make_hit("job-1", 1.0, KEYWORD)],
        [make_hit("job-1", 0.5, SEMANTIC)],
    )

    assert candidates[0].retrieval_score == pytest.approx(0.8 * 1.0 + 0.2 * 0.5)


def test_min_retrieval_score_filters_candidates() -> None:
    service = BaselineMatchingService(MatchingConfig(min_retrieval_score=0.5))

    candidates = service.merge_candidates(
        [make_hit("job-1", 0.6, KEYWORD), make_hit("job-2", 1.0, KEYWORD)],
        [],
    )

    assert [candidate.job_id for candidate in candidates] == ["job-2"]


def test_max_candidates_caps_result() -> None:
    service = BaselineMatchingService(MatchingConfig(max_candidates=2))

    candidates = service.merge_candidates(
        [make_hit(f"job-{index}", 1.0, KEYWORD) for index in range(5)],
        [],
    )

    assert len(candidates) == 2


def test_channel_mismatch_raises() -> None:
    with pytest.raises(ValueError, match="channel"):
        BaselineMatchingService().merge_candidates(
            [make_hit("job-1", 0.8, SEMANTIC)],
            [],
        )


def test_duplicate_job_within_one_channel_raises() -> None:
    with pytest.raises(ValueError, match="duplicate"):
        BaselineMatchingService().merge_candidates(
            [make_hit("job-1", 0.8, KEYWORD), make_hit("job-1", 0.6, KEYWORD)],
            [],
        )


def test_invalid_config_rejected() -> None:
    with pytest.raises(ValueError, match="sum to 1.0"):
        MatchingConfig(keyword_weight=0.7, semantic_weight=0.7)
