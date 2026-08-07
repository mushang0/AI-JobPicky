from __future__ import annotations

import asyncio
from typing import cast

import pytest
from catalog.factories import make_job
from matching.factories import make_profile

from jobpicky.contracts import Candidate, ConstraintStatus, ErrorCode, RetrievalChannel
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
    assessment_schema = output_schema["properties"]["assessments"]["items"]
    assert set(assessment_schema["properties"]) == {
        "job_id",
        "matched",
        "match_score",
        "reason",
        "gaps",
    }
    assert "retrieval_score" not in prompt
    assert "学历" in prompt
    assert "matched_strengths" not in assessment_schema["properties"]
    assert "evidence" not in assessment_schema["properties"]
    assert "evidence_details" not in assessment_schema["properties"]
    assert "constraint_conclusions" not in assessment_schema["properties"]


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


def test_evaluator_replaces_model_constraint_conclusions_with_backend_facts() -> None:
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
                        "constraint_conclusions": {"education": "NOT_SATISFIED"},
                    }
                ]
            }
        )
        result = await DashScopeJobEvaluator(chat_model=chat).evaluate(
            make_profile(), [make_job()], [_candidate()]
        )
        assert result[0].matched is True
        assert result[0].constraint_conclusions["education"] == ConstraintStatus.SATISFIED
        assert result[0].matched_strengths == []
        assert result[0].evidence == []

    asyncio.run(check())


def test_evaluator_hard_constraint_can_override_model_match() -> None:
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
                        "constraint_conclusions": {"education": "SATISFIED"},
                    }
                ]
            }
        )
        result = await DashScopeJobEvaluator(chat_model=chat).evaluate(
            make_profile(education="本科"),
            [make_job(education_requirement="硕士")],
            [_candidate()],
        )
        assert result[0].matched is False
        assert result[0].constraint_conclusions["education"] == ConstraintStatus.NOT_SATISFIED

    asyncio.run(check())


def test_evaluator_retries_invalid_output_with_validation_feedback() -> None:
    class RepairChat:
        def __init__(self) -> None:
            self.calls = 0
            self.messages: list[object] = []

        async def ainvoke(self, messages: object) -> object:
            self.calls += 1
            self.messages.append(messages)
            if self.calls == 1:
                return {
                    "assessments": [
                        {
                            "job_id": "job-1",
                            "matched": True,
                            "match_score": 88,
                            "reason": "相关经验充分",
                            "matched_strengths": ["Python"],
                            "gaps": "需要修复为数组",
                        }
                    ]
                }
            return {
                "assessments": [
                    {
                        "job_id": "job-1",
                        "matched": True,
                        "match_score": 88,
                        "reason": "相关经验充分",
                        "matched_strengths": ["Python"],
                        "gaps": [],
                    }
                ]
            }

    async def check() -> None:
        chat = RepairChat()
        result = await DashScopeJobEvaluator(chat_model=chat).evaluate(
            make_profile(), [make_job()], [_candidate()]
        )
        assert result[0].matched is True
        assert chat.calls == 2
        repair_message = cast(list[tuple[str, str]], chat.messages[1])[-1][1]
        assert "gaps" in repair_message

    asyncio.run(check())


def test_evaluator_removes_education_gaps_from_model_output() -> None:
    payload = {
        "assessments": [
            {
                "job_id": "job-1",
                "matched": True,
                "match_score": 88,
                "reason": "岗位方向匹配",
                "gaps": ["教育背景为硕士，岗位要求为本科；存在学历差距"],
            }
        ]
    }

    async def check() -> None:
        chat = FakeChat(payload)
        result = await DashScopeJobEvaluator(chat_model=chat).evaluate(
            make_profile(education="硕士"),
            [make_job(education_requirement="本科")],
            [_candidate()],
        )
        assert chat.calls == 1
        assert result[0].gaps == []

    asyncio.run(check())


def test_evaluator_reports_candidate_mapping_failure_separately() -> None:
    payload = {
        "assessments": [
            {
                "job_id": "unknown",
                "matched": True,
                "match_score": 80,
                "reason": "x",
                "gaps": [],
            }
        ]
    }

    async def check() -> None:
        with pytest.raises(ApplicationError) as error:
            await DashScopeJobEvaluator(chat_model=FakeChat(payload)).evaluate(
                make_profile(), [make_job()], [_candidate()]
            )
        assert error.value.details["failure_kind"] == "candidate_mapping"

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
        assert error.value.details["stage"] == "EVALUATE"
        assert error.value.details["validation_attempts"] == 2

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


def test_evaluator_reports_provider_timeout_after_retry_budget() -> None:
    async def check() -> None:
        with pytest.raises(ApplicationError) as error:
            await DashScopeJobEvaluator(
                chat_model=FakeChat(TimeoutError()),
                max_retries=1,
            ).evaluate(make_profile(), [make_job()], [_candidate()])

        assert error.value.details == {
            "stage": "EVALUATE",
            "failure_kind": "provider_timeout",
            "provider_attempts": 2,
            "retryable": True,
        }

    asyncio.run(check())
