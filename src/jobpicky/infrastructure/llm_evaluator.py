from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from ..contracts import (
    Candidate,
    ErrorCode,
    EvaluationResponse,
    JobFact,
    MatchAssessment,
    ProfileSnapshot,
    validate_assessments,
)
from ..errors import ApplicationError
from .evaluation_resources import load_evaluation_output_schema, load_evaluation_prompt


class DashScopeJobEvaluator:
    """DashScope OpenAI-compatible evaluator with a strict DTO boundary."""

    def __init__(
        self,
        *,
        provider: str = "dashscope",
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_seconds: float = 30.0,
        max_retries: int = 1,
        chat_model: Any | None = None,
    ) -> None:
        self._provider = provider
        self._model_name = model
        self._api_key = api_key
        self._base_url = base_url
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._chat_model = chat_model
        self._structured_model: Any | None = None

    async def evaluate(
        self,
        profile: ProfileSnapshot,
        jobs: Sequence[JobFact],
        candidates: Sequence[Candidate],
        effective_extra_request: str | None = None,
    ) -> list[MatchAssessment]:
        candidate_ids = [candidate.job_id for candidate in candidates]
        job_by_id = {job.id: job for job in jobs}
        if len(job_by_id) != len(jobs) or any(job_id not in job_by_id for job_id in candidate_ids):
            raise self._evaluation_error("candidate and job facts do not form a complete set")

        payload = self._build_input(
            profile,
            jobs,
            candidates,
            effective_extra_request=effective_extra_request,
        )
        raw = await self._invoke_with_retries(payload)
        try:
            response = EvaluationResponse.model_validate(self._extract_payload(raw))
        except (TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
            raise self._evaluation_error("evaluator returned invalid structured output") from exc
        try:
            return validate_assessments(candidate_ids, response.assessments)
        except ValueError as exc:
            raise self._evaluation_error(
                "evaluator job IDs did not match the candidate batch"
            ) from exc

    async def _invoke_with_retries(self, payload: dict[str, Any]) -> Any:
        messages = [
            ("system", load_evaluation_prompt()),
            ("human", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        ]
        model = self._get_chat_model()
        attempts = self._max_retries + 1
        for attempt in range(attempts):
            try:
                invocation = self._ainvoke(model, messages)
                return await asyncio.wait_for(invocation, timeout=self._timeout_seconds)
            except Exception as exc:
                if attempt + 1 >= attempts or not _is_retryable_provider_error(exc):
                    raise self._evaluation_error("evaluator provider request failed") from exc
        raise AssertionError("unreachable")

    async def _ainvoke(self, model: Any, messages: list[tuple[str, str]]) -> Any:
        if hasattr(model, "ainvoke"):
            return await model.ainvoke(messages)
        if hasattr(model, "invoke"):
            return await asyncio.to_thread(model.invoke, messages)
        raise self._evaluation_error("evaluator client does not support invocation")

    def _get_chat_model(self) -> Any:
        if self._structured_model is not None:
            return self._structured_model
        if self._chat_model is not None:
            # Test doubles and custom adapters may already return JSON.  They
            # are kept unwrapped so the same strict application validation is
            # exercised offline as in production.
            self._structured_model = self._chat_model
            return self._structured_model
        if self._provider != "dashscope":
            raise self._dependency_error("unsupported LLM provider")
        if not self._model_name:
            raise self._dependency_error("LLM model is not configured")
        if not self._api_key:
            raise self._dependency_error("DashScope API key is not configured")
        try:
            from importlib import import_module

            ChatOpenAI = import_module("langchain_openai").ChatOpenAI

            model = ChatOpenAI(
                model=self._model_name,
                api_key=self._api_key,
                base_url=self._base_url,
                timeout=self._timeout_seconds,
                # Retries are owned by _invoke_with_retries so the configured
                # budget is not applied once here and again outside.
                max_retries=0,
                temperature=0,
                model_kwargs={"response_format": {"type": "json_object"}},
                extra_body={"enable_thinking": False},
            )
            self._structured_model = model.with_structured_output(
                load_evaluation_output_schema(),
                method="json_mode",
            )
        except Exception as exc:
            raise self._dependency_error("DashScope evaluator could not be initialized") from exc
        return self._structured_model

    @staticmethod
    def _build_input(
        profile: ProfileSnapshot,
        jobs: Sequence[JobFact],
        candidates: Sequence[Candidate],
        *,
        effective_extra_request: str | None,
    ) -> dict[str, Any]:
        jobs_by_id = {job.id: job for job in jobs}
        candidate_payload = []
        for candidate in candidates:
            job = jobs_by_id[candidate.job_id]
            candidate_payload.append(
                {
                    "job_id": candidate.job_id,
                    "retrieval_score": candidate.retrieval_score,
                    "keyword_score": candidate.keyword_score,
                    "semantic_score": candidate.semantic_score,
                    "sources": [str(source) for source in candidate.sources],
                    "job": {
                        "id": job.id,
                        "company_name": job.company_name,
                        "title": job.title,
                        "locations": job.locations,
                        "description": job.description,
                        "recruitment_type": job.recruitment_type,
                        "education_requirement": job.education_requirement,
                        "salary_min": job.salary_min,
                        "salary_max": job.salary_max,
                        "salary_months": job.salary_months,
                        "graduation_years": job.graduation_years,
                    },
                }
            )
        return {
            "profile": {
                "target_locations": profile.target_locations,
                "target_roles": profile.target_roles,
                "skills": profile.skills,
                "excluded_roles": profile.excluded_roles,
                "education": profile.education,
                "graduation_year": profile.graduation_year,
                "expected_salary_min": profile.expected_salary_min,
                "experience_summary": profile.experience_summary,
                "warnings": profile.warnings,
                "extra_request": effective_extra_request,
            },
            "candidates": candidate_payload,
        }

    @staticmethod
    def _extract_payload(response: Any) -> Any:
        if isinstance(response, EvaluationResponse):
            return response.model_dump(mode="python")
        if isinstance(response, BaseModel):
            return response.model_dump(mode="python")
        if isinstance(response, dict):
            return response

        tool_calls = getattr(response, "tool_calls", None)
        if not tool_calls:
            additional_kwargs = getattr(response, "additional_kwargs", {})
            tool_calls = (
                additional_kwargs.get("tool_calls") if isinstance(additional_kwargs, dict) else None
            )
        if tool_calls:
            first_call = tool_calls[0]
            arguments = first_call.get("args") if isinstance(first_call, dict) else None
            if arguments is None and isinstance(first_call, dict):
                function = first_call.get("function")
                arguments = function.get("arguments") if isinstance(function, dict) else None
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if arguments is not None:
                return arguments

        content = getattr(response, "content", response)
        if isinstance(content, dict):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            content = "".join(parts)
        if isinstance(content, str):
            return json.loads(content)
        raise ValueError("evaluator response did not contain JSON content")

    @staticmethod
    def _dependency_error(message: str) -> ApplicationError:
        return ApplicationError(
            ErrorCode.DEPENDENCY_UNAVAILABLE,
            message,
            status_code=503,
            details={"dependency": "llm", "stage": "EVALUATE"},
        )

    @staticmethod
    def _evaluation_error(message: str) -> ApplicationError:
        return ApplicationError(
            ErrorCode.RECOMMENDATION_FAILED,
            message,
            status_code=502,
            details={"stage": "EVALUATE"},
        )


def _is_retryable_provider_error(exc: Exception) -> bool:
    if isinstance(exc, TimeoutError):
        return True
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, str) and status.isdigit():
        status = int(status)
    if isinstance(status, int):
        return status == 429 or 500 <= status <= 599
    text = str(exc).lower()
    return "timeout" in text or "429" in text or any(f"{code}" in text for code in range(500, 600))


__all__ = ["DashScopeJobEvaluator"]
