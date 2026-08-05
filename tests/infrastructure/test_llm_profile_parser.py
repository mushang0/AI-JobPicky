import asyncio
from typing import Any

import pytest

from jobpicky.contracts import ErrorCode
from jobpicky.errors import ApplicationError
from jobpicky.infrastructure.llm_profile_parser import DashScopeProfileParser


class FakeChat:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.messages: list[tuple[str, Any]] = []

    async def ainvoke(self, messages: list[tuple[str, Any]]) -> object:
        self.messages = messages
        return self.payload


def test_profile_parser_validates_model_output_and_marks_missing_fields() -> None:
    async def check() -> None:
        chat = FakeChat(
            {
                "draft": {
                    "target_roles": ["Python 后端工程师"],
                    "skills": ["Python", "FastAPI"],
                    "experience_summary": "使用 FastAPI 开发过后端接口。",
                },
                "warnings": [],
            }
        )
        result = await DashScopeProfileParser(chat_model=chat).parse(
            "候选人使用 Python 和 FastAPI 开发过后端接口。"
        )

        assert result.draft.target_roles == ["Python 后端工程师"]
        assert any("目标城市" in warning for warning in result.warnings)
        assert "resume_text" in chat.messages[-1][1]

    asyncio.run(check())


def test_profile_parser_sends_rendered_pages_as_multimodal_content() -> None:
    async def check() -> None:
        chat = FakeChat(
            {
                "draft": {
                    "target_roles": ["Python 后端工程师"],
                    "skills": ["Python"],
                    "experience_summary": "使用 Python 开发后端接口。",
                },
                "warnings": [],
            }
        )

        result = await DashScopeProfileParser(chat_model=chat).parse_images(
            [b"\x89PNG\r\n\x1a\nresume-page"],
        )

        assert result.draft.target_roles == ["Python 后端工程师"]
        content = chat.messages[-1][1]
        assert isinstance(content, list)
        assert content[0]["type"] == "text"
        assert content[1]["type"] == "image_url"
        assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
        assert "languages" in chat.messages[0][1]
        assert '"draft"' in chat.messages[0][1]
        assert "输出格式示例" in chat.messages[0][1]

    asyncio.run(check())


def test_profile_parser_normalizes_a_flat_model_response_without_identity_fields() -> None:
    async def check() -> None:
        chat = FakeChat(
            {
                "name": "不应进入画像",
                "phone": "13800000000",
                "education_level": "硕士",
                "target_roles": ["计算机视觉算法工程师"],
                "skills": ["Python"],
                "experience_summary": "负责视觉算法项目。",
                "warnings": [],
            }
        )

        result = await DashScopeProfileParser(chat_model=chat).parse_images([b"png"])

        assert result.draft.target_roles == ["计算机视觉算法工程师"]
        assert result.draft.education == "硕士"
        assert result.draft.skills == ["Python"]
        assert all("13800000000" not in warning for warning in result.warnings)
        assert any("Schema 未定义" in warning for warning in result.warnings)

    asyncio.run(check())


def test_profile_parser_filters_extra_fields_inside_nested_draft() -> None:
    async def check() -> None:
        chat = FakeChat(
            {
                "draft": {
                    "target_roles": ["计算机视觉算法工程师"],
                    "skills": ["Python"],
                    "experience_summary": "负责视觉算法项目。",
                    "languages": ["Python"],
                    "frameworks": ["PyTorch"],
                    "experience_years": 2,
                },
                "warnings": [],
            }
        )

        result = await DashScopeProfileParser(chat_model=chat).parse_images([b"png"])

        assert result.draft.target_roles == ["计算机视觉算法工程师"]
        assert result.draft.skills == ["Python"]
        assert any("Schema 未定义" in warning for warning in result.warnings)

    asyncio.run(check())


def test_profile_parser_rejects_invalid_model_fields_after_filtering_extras() -> None:
    async def check() -> None:
        parser = DashScopeProfileParser(
            chat_model=FakeChat(
                {
                    "draft": {
                        "target_roles": "后端工程师",
                        "skills": ["Python"],
                        "phone": "13800000000",
                    },
                    "warnings": [],
                }
            )
        )
        with pytest.raises(ApplicationError) as invalid:
            await parser.parse("Python 后端工程师，熟悉接口开发。")
        assert invalid.value.code == str(ErrorCode.PROFILE_PARSE_FAILED)
        assert invalid.value.status_code == 502

    asyncio.run(check())


def test_profile_parser_reports_missing_llm_configuration() -> None:
    async def check() -> None:
        with pytest.raises(ApplicationError) as unavailable:
            await DashScopeProfileParser().parse("Python 后端工程师，熟悉接口开发。")

        assert unavailable.value.code == str(ErrorCode.DEPENDENCY_UNAVAILABLE)
        assert unavailable.value.status_code == 503

    asyncio.run(check())
