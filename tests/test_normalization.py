import pytest
from pydantic import ValidationError

from jobpicky.contracts import (
    JobListQuery,
    normalize_city,
    normalize_company_nature,
    normalize_education,
    normalize_locations,
    normalize_recruitment_type,
    normalize_search_text,
    normalize_tags,
)


def test_text_and_tags_use_nfkc_whitespace_and_case_insensitive_deduplication() -> None:
    assert normalize_search_text("  Ｐｙｔｈｏｎ\t 后端  ") == "Python 后端"
    assert normalize_tags([" Python ", "python", "后端\t开发"]) == ["Python", "后端 开发"]


def test_city_and_locations_normalize_aliases_and_preserve_order() -> None:
    assert normalize_city(" 北京市 ") == "北京"
    assert normalize_city("线上") == "远程"
    assert normalize_city("全国多地") == "全国"
    assert normalize_city("工作地点不限") is None
    assert normalize_locations(["北京市、上海市", " 北京 ", "未知", "线上"]) == [
        "北京",
        "上海",
        "远程",
    ]


def test_company_nature_maps_only_confirmed_aliases() -> None:
    assert normalize_company_nature("民企") == "民营企业"
    assert normalize_company_nature("国有企业") == "国企"
    assert normalize_company_nature("外企") == "外资企业"
    assert normalize_company_nature("合资") == "合资企业"
    assert normalize_company_nature("央国企") is None
    assert normalize_company_nature("社会组织") is None


def test_recruitment_type_rejects_mixed_or_unknown_categories() -> None:
    assert normalize_recruitment_type("校园招聘") == "校招"
    assert normalize_recruitment_type("社会招聘") == "社招"
    assert normalize_recruitment_type("暑期实习") == "实习"
    assert normalize_recruitment_type("实习、秋招提前批") is None
    assert normalize_recruitment_type("灵活招聘") is None


def test_education_uses_lowest_explicit_admission_level_and_keeps_unknown_unknown() -> None:
    assert normalize_education("大专") == "专科"
    assert normalize_education("本科、硕士、博士") == "本科"
    assert normalize_education("硕士研究生、博士研究生") == "硕士"
    assert normalize_education("博士研究生") == "博士"
    assert normalize_education("本科，专业不限") == "本科"
    assert normalize_education("学历不限") is None
    assert normalize_education("学历不限，本科优先") is None
    assert normalize_education("研究生") is None


def test_job_list_query_normalizes_filter_aliases_before_validation() -> None:
    query = JobListQuery.model_validate(
        {
            "q": " " * 201 + "Ｐｙｔｈｏｎ",
            "city": ["北京市", "北京"],
            "company_nature": ["民企"],
            "recruitment_type": ["社会招聘"],
            "education": ["大专"],
        }
    )
    assert query.q == "Python"
    assert query.city == ["北京"]
    assert query.company_nature == ["民营企业"]
    assert query.recruitment_type == ["社招"]
    assert query.education == ["专科"]

    with pytest.raises(ValidationError):
        JobListQuery.model_validate({"recruitment_type": ["实习、校招"]})
