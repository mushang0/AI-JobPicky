import asyncio

import pytest

from jobpicky.contracts import ErrorCode
from jobpicky.errors import ApplicationError
from jobpicky.infrastructure.llm_profile_parser import DashScopeProfileParser


class FakeChat:
    def __init__(self, payload: object) -> None:
        self.payload = payload
        self.messages: list[tuple[str, str]] = []

    async def ainvoke(self, messages: list[tuple[str, str]]) -> object:
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


def test_profile_parser_rejects_unknown_or_invalid_model_fields() -> None:
    async def check() -> None:
        parser = DashScopeProfileParser(
            chat_model=FakeChat(
                {
                    "draft": {
                        "target_roles": ["后端工程师"],
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
