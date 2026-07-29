import pytest

from jobpicky.collection.link_extraction import extract_links


@pytest.mark.parametrize(
    ("value", "hyperlink_target", "expected"),
    [
        # mailto 只算一条，不再重复拆出裸邮箱
        ("mailto:hr@example.com", None, ["mailto:hr@example.com"]),
        ("mailto:hr@example.com?subject=apply", None, ["mailto:hr@example.com?subject=apply"]),
        # 纯文本邮箱
        ("邮箱投递：hr@example.com", None, ["hr@example.com"]),
        # URL 里带的邮箱不重复，独立邮箱保留
        (
            "https://example.com/apply?mail=a@b.com 或联系 c@d.com",
            None,
            ["https://example.com/apply?mail=a@b.com", "c@d.com"],
        ),
        # 一个单元格多个 URL
        (
            "https://a.example.com/jobs，https://b.example.com/jobs",
            None,
            ["https://a.example.com/jobs", "https://b.example.com/jobs"],
        ),
        # 尾部中文标点剥离
        ("https://a.example.com/jobs。", None, ["https://a.example.com/jobs"]),
        # 单元格文本与超链接目标相同则去重
        (
            "https://a.example.com/jobs",
            "https://a.example.com/jobs",
            ["https://a.example.com/jobs"],
        ),
        # 有超链接目标时，无链接的文本不兜底保留
        ("点击投递", "https://a.example.com/jobs", ["https://a.example.com/jobs"]),
        # 无链接文本原样保留
        ("官网投递", None, ["官网投递"]),
        ("", None, []),
        (None, None, []),
    ],
)
def test_extract_links(value: object, hyperlink_target: str | None, expected: list[str]) -> None:
    assert extract_links(value, hyperlink_target) == expected


def test_mailto_not_duplicated_with_trailing_punctuation() -> None:
    assert extract_links("mailto:hr@example.com。", None) == ["mailto:hr@example.com"]
