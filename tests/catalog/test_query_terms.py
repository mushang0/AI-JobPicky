from __future__ import annotations

from jobpicky.catalog import extract_terms, term_hit_score

from .factories import make_job


def test_extract_terms_splits_cjk_and_latin() -> None:
    terms = extract_terms("后端工程师\nPython, PostgreSQL 开发")
    assert terms == ["后端工程师", "python", "postgresql", "开发"]


def test_extract_terms_dedupes_case_insensitively() -> None:
    assert extract_terms("Python python PYTHON") == ["python"]


def test_extract_terms_drops_single_characters() -> None:
    assert extract_terms("3 年后端经验") == ["年后端经验"]


def test_extract_terms_keeps_skill_symbols() -> None:
    assert "c++" in extract_terms("熟悉 C++ 与 k8s")


def test_extract_terms_empty_input() -> None:
    assert extract_terms("") == []
    assert extract_terms("  \n，。 ") == []


def test_term_hit_score_full_match() -> None:
    job = make_job(title="后端工程师", company_name="示例科技")
    assert term_hit_score(["后端工程师", "示例科技"], job) == 1.0


def test_term_hit_score_partial_match() -> None:
    job = make_job(title="后端工程师", description="负责 Python 服务开发")
    score = term_hit_score(["后端工程师", "python", "不存在词"], job)
    assert score == 2 / 3


def test_term_hit_score_searches_company_and_description() -> None:
    job = make_job(company_name="示例科技", description="使用 PostgreSQL 存储")
    assert term_hit_score(["示例科技", "postgresql"], job) == 1.0


def test_term_hit_score_handles_missing_description() -> None:
    job = make_job(description=None)
    assert term_hit_score(["后端工程师"], job) == 1.0
    assert term_hit_score(["其他词"], job) == 0.0


def test_term_hit_score_empty_terms() -> None:
    assert term_hit_score([], make_job()) == 0.0
