from __future__ import annotations

import asyncio
from typing import cast

import pytest
from catalog.factories import make_job
from matching.factories import make_profile

from jobpicky.contracts import Candidate, ErrorCode, RetrievalChannel
from jobpicky.errors import ApplicationError
from jobpicky.infrastructure.evaluation_resources import (
    load_evaluation_input_schema,
    load_evaluation_output_schema,
    load_evaluation_prompt,
)
from jobpicky.infrastructure.llm_evaluator import DashScopeJobEvaluator


def _candidate(job_id: str = "job-1") -> Candidate:
    return Candidate(
        job_id=job_id,
        retrieval_score=0.8,
        sources=[RetrievalChannel.KEYWORD],
    )


def test_evaluation_prompt_and_schemas_are_external_resources() -> None:
    prompt = load_evaluation_prompt()
    input_schema = load_evaluation_input_schema()
    output_schema = load_evaluation_output_schema()

    assert "{{INPUT_SCHEMA}}" not in prompt
    assert "{{OUTPUT_SCHEMA}}" not in prompt
    assert "target_locations" in prompt
    assert "assessments" in prompt
    assert input_schema["required"] == ["profile", "candidates"]
    assert set(output_schema["properties"]) == {"assessments"}


class FakeChat:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls = 0
        self.messages: list[object] = []

    async def ainvoke(self, messages: object) -> object:
        self.calls += 1
        self.messages.append(messages)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def test_evaluator_accepts_only_strict_assessment_json() -> None:
    async def check() -> None:
        chat = FakeChat(
            {
                "assessments": [
                    {
                        "job_id": "job-1",
                        "matched": True,
                        "match_score": 88,
                        "reason": "相关经验充分",
                        "matched_strengths": ["Python"],
                        "gaps": [],
                        "evidence": ["后端开发经验"],
                    }
                ]
            }
        )
        result = await DashScopeJobEvaluator(chat_model=chat).evaluate(
            make_profile(),
            [make_job()],
            [_candidate()],
            "只看英文岗位",
        )
        assert result[0].job_id == "job-1"
        assert chat.calls == 1
        system_message = cast(list[tuple[str, str]], chat.messages[0])[0][1]
        assert "{{INPUT_SCHEMA}}" not in system_message
        assert "target_locations" in system_message

    asyncio.run(check())


@pytest.mark.parametrize(
    "payload",
    [
        {
            "assessments": [
                {
                    "job_id": "unknown",
                    "matched": True,
                    "match_score": 80,
                    "reason": "x",
                    "matched_strengths": [],
                    "gaps": [],
                }
            ]
        },
        {
            "assessments": [
                {
                    "job_id": "job-1",
                    "matched": True,
                    "match_score": 80,
                    "reason": "x",
                    "matched_strengths": [],
                    "gaps": [],
                    "company_name": "幻觉",
                }
            ]
        },
        {
            "assessments": [
                {
                    "job_id": "job-1",
                    "matched": True,
                    "match_score": 101,
                    "reason": "x",
                    "matched_strengths": [],
                    "gaps": [],
                }
            ]
        },
    ],
)
def test_evaluator_rejects_unknown_or_hallucinated_output(payload: object) -> None:
    async def check() -> None:
        with pytest.raises(ApplicationError) as error:
            await DashScopeJobEvaluator(chat_model=FakeChat(payload)).evaluate(
                make_profile(), [make_job()], [_candidate()]
            )
        assert error.value.code == str(ErrorCode.RECOMMENDATION_FAILED)
        assert error.value.details == {"stage": "EVALUATE"}

    asyncio.run(check())


def test_evaluator_retries_provider_timeout_once() -> None:
    class RetryChat:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages: object) -> object:
            self.calls += 1
            if self.calls == 1:
                raise TimeoutError()
            return {
                "assessments": [
                    {
                        "job_id": "job-1",
                        "matched": False,
                        "match_score": 20,
                        "reason": "证据不足",
                        "matched_strengths": [],
                        "gaps": ["缺少证据"],
                    }
                ]
            }

    async def check() -> None:
        chat = RetryChat()
        result = await DashScopeJobEvaluator(chat_model=chat, max_retries=1).evaluate(
            make_profile(), [make_job()], [_candidate()]
        )
        assert result[0].matched is False
        assert chat.calls == 2

    asyncio.run(check())
