from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, ValidationError

from ..contracts import (
    Candidate,
    ConstraintStatus,
    ErrorCode,
    EvaluationResponse,
    JobFact,
    MatchAssessment,
    ProfileSnapshot,
    validate_assessments,
)
from ..contracts.common import JobStatus, JsonObject
from ..errors import ApplicationError
from .evaluation_resources import load_evaluation_output_schema, load_evaluation_prompt

_OUTPUT_VALIDATION_RETRIES = 1


class _CandidateMappingValidationError(ValueError):
    pass


class DashScopeJobEvaluator:
    """DashScope OpenAI-compatible evaluator with a strict DTO boundary."""

    def __init__(
        self,
        *,
        provider: str = "dashscope",
        model: str | None = None,
        api_key: str | None = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        timeout_seconds: float = 180.0,
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
            raise self._evaluation_error(
                "candidate and job facts do not form a complete set",
                failure_kind="candidate_mapping",
            )

        payload = self._build_input(
            profile,
            jobs,
            candidates,
            effective_extra_request=effective_extra_request,
        )
        repair_hint: str | None = None
        for attempt in range(_OUTPUT_VALIDATION_RETRIES + 1):
            raw = await self._invoke_with_retries(payload, repair_hint=repair_hint)
            try:
                raw_payload = _without_model_owned_fields(self._extract_payload(raw))
                response = EvaluationResponse.model_validate(raw_payload)
                try:
                    assessments = validate_assessments(candidate_ids, response.assessments)
                except ValueError as exc:
                    raise _CandidateMappingValidationError(str(exc)) from exc
                assessments = _apply_backend_constraints(payload, assessments)
                return assessments
            except (TypeError, ValueError, ValidationError, json.JSONDecodeError) as exc:
                if attempt == _OUTPUT_VALIDATION_RETRIES:
                    raise self._evaluation_error(
                        "evaluator output did not match the required structure or candidate facts",
                        failure_kind=_validation_failure_kind(exc),
                        details={"validation_attempts": attempt + 1},
                    ) from exc
                repair_hint = _format_validation_error(exc)
        raise AssertionError("unreachable")

    async def _invoke_with_retries(
        self,
        payload: dict[str, Any],
        *,
        repair_hint: str | None = None,
    ) -> Any:
        messages = [
            ("system", load_evaluation_prompt()),
            ("human", json.dumps(payload, ensure_ascii=False, separators=(",", ":"))),
        ]
        if repair_hint:
            messages.append(
                (
                    "human",
                    "上一次输出未通过本地结构校验。请只输出修正后的完整 JSON，不要解释。"
                    f"校验提示：{repair_hint}",
                )
            )
        model = self._get_chat_model()
        attempts = self._max_retries + 1
        for attempt in range(attempts):
            try:
                invocation = self._ainvoke(model, messages)
                return await asyncio.wait_for(invocation, timeout=self._timeout_seconds)
            except Exception as exc:
                if attempt + 1 >= attempts or not _is_retryable_provider_error(exc):
                    raise self._evaluation_error(
                        "evaluator provider request failed",
                        failure_kind=_provider_failure_kind(exc),
                        details={
                            "provider_attempts": attempt + 1,
                            "retryable": _is_retryable_provider_error(exc),
                        },
                    ) from exc
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
                    "constraint_checks": _constraint_checks(profile, job),
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
                        "status": job.status,
                    },
                }
            )
        return {
            "profile": {
                "target_locations": profile.target_locations,
                "target_roles": profile.target_roles,
                "recruitment_types": profile.recruitment_types,
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
    def _evaluation_error(
        message: str,
        *,
        failure_kind: str | None = None,
        details: JsonObject | None = None,
    ) -> ApplicationError:
        error_details: JsonObject = {"stage": "EVALUATE"}
        if failure_kind is not None:
            error_details["failure_kind"] = failure_kind
        error_details.update(details or {})
        return ApplicationError(
            ErrorCode.RECOMMENDATION_FAILED,
            message,
            status_code=502,
            details=error_details,
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


def _format_validation_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:1200]


def _validation_failure_kind(exc: Exception) -> str:
    if isinstance(exc, _CandidateMappingValidationError):
        return "candidate_mapping"
    if isinstance(exc, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(exc, (ValidationError, TypeError)):
        return "schema_validation"
    return "output_validation"


def _provider_failure_kind(exc: Exception) -> str:
    text = str(exc).lower()
    if isinstance(exc, TimeoutError) or "timeout" in text:
        return "provider_timeout"
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if isinstance(status, str) and status.isdigit():
        status = int(status)
    if status == 429 or "429" in text:
        return "provider_rate_limit"
    if isinstance(status, int) and 500 <= status <= 599:
        return "provider_5xx"
    if any(f"{code}" in text for code in range(500, 600)):
        return "provider_5xx"
    return "provider_request"


_EDUCATION_LEVELS = {
    "专科": 1,
    "大专": 1,
    "本科": 2,
    "学士": 2,
    "硕士": 3,
    "研究生": 3,
    "博士": 4,
}


def _education_level(value: str | None) -> int | None:
    if not value:
        return None
    return max(
        (level for keyword, level in _EDUCATION_LEVELS.items() if keyword in value),
        default=None,
    )


def _constraint(
    status: ConstraintStatus,
    candidate_value: object,
    job_value: object,
) -> dict[str, object]:
    return {
        "status": status,
        "candidate_value": candidate_value,
        "job_value": job_value,
    }


def _constraint_checks(profile: ProfileSnapshot, job: JobFact) -> dict[str, dict[str, object]]:
    location_status = ConstraintStatus.UNKNOWN
    if profile.target_locations and job.locations:
        location_status = (
            ConstraintStatus.SATISFIED
            if set(profile.target_locations) & set(job.locations)
            else ConstraintStatus.NOT_SATISFIED
        )

    recruitment_status = ConstraintStatus.UNKNOWN
    if profile.recruitment_types and job.recruitment_type is not None:
        recruitment_status = (
            ConstraintStatus.SATISFIED
            if job.recruitment_type in profile.recruitment_types
            else ConstraintStatus.NOT_SATISFIED
        )

    education_status = ConstraintStatus.UNKNOWN
    candidate_education_level = _education_level(profile.education)
    required_education_level = _education_level(job.education_requirement)
    if candidate_education_level is not None and required_education_level is not None:
        education_status = (
            ConstraintStatus.SATISFIED
            if required_education_level <= candidate_education_level
            else ConstraintStatus.NOT_SATISFIED
        )

    graduation_status = ConstraintStatus.UNKNOWN
    if profile.graduation_year is not None and job.graduation_years:
        graduation_status = (
            ConstraintStatus.SATISFIED
            if profile.graduation_year in job.graduation_years
            else ConstraintStatus.NOT_SATISFIED
        )

    salary_status = ConstraintStatus.UNKNOWN
    if profile.expected_salary_min is not None and job.salary_max is not None:
        salary_status = (
            ConstraintStatus.SATISFIED
            if job.salary_max >= profile.expected_salary_min
            else ConstraintStatus.NOT_SATISFIED
        )

    excluded_role_status = ConstraintStatus.SATISFIED
    if any(role.casefold() in job.title.casefold() for role in profile.excluded_roles):
        excluded_role_status = ConstraintStatus.NOT_SATISFIED

    return {
        "location": _constraint(
            location_status,
            profile.target_locations,
            job.locations,
        ),
        "recruitment_type": _constraint(
            recruitment_status,
            profile.recruitment_types,
            job.recruitment_type,
        ),
        "education": _constraint(
            education_status,
            profile.education,
            job.education_requirement,
        ),
        "graduation_year": _constraint(
            graduation_status,
            profile.graduation_year,
            job.graduation_years,
        ),
        "salary": _constraint(
            salary_status,
            profile.expected_salary_min,
            job.salary_max,
        ),
        "excluded_role": _constraint(
            excluded_role_status,
            profile.excluded_roles,
            job.title,
        ),
        "status": _constraint(
            ConstraintStatus.SATISFIED
            if job.status == JobStatus.OPEN
            else ConstraintStatus.NOT_SATISFIED,
            JobStatus.OPEN,
            job.status,
        ),
    }


def _without_model_owned_fields(payload: Any) -> Any:
    """Keep objective facts and repetitive evidence owned outside model output."""
    if not isinstance(payload, dict) or not isinstance(payload.get("assessments"), list):
        return payload
    sanitized = dict(payload)
    ignored_fields = {
        "constraint_conclusions",
        "matched_strengths",
        "evidence",
        "evidence_details",
    }
    sanitized["assessments"] = [
        {key: value for key, value in assessment.items() if key not in ignored_fields}
        if isinstance(assessment, dict)
        else assessment
        for assessment in payload["assessments"]
    ]
    return sanitized


def _apply_backend_constraints(
    payload: dict[str, Any],
    assessments: Sequence[MatchAssessment],
) -> list[MatchAssessment]:
    """Attach deterministic facts and prevent hard-constraint overrides."""
    checks_by_job = {
        str(candidate["job_id"]): candidate.get("constraint_checks", {})
        for candidate in payload.get("candidates", [])
    }
    corrected: list[MatchAssessment] = []
    for assessment in assessments:
        checks = checks_by_job.get(assessment.job_id)
        if not isinstance(checks, dict):
            corrected.append(
                assessment.model_copy(
                    update={
                        "gaps": [gap for gap in assessment.gaps if not _is_education_gap_text(gap)]
                    }
                )
            )
            continue
        conclusions: dict[str, ConstraintStatus] = {}
        has_hard_violation = False
        for name, check in checks.items():
            if not isinstance(check, dict) or "status" not in check:
                continue
            status = ConstraintStatus(str(check["status"]))
            conclusions[name] = status
            has_hard_violation |= status == ConstraintStatus.NOT_SATISFIED
        gaps = [gap for gap in assessment.gaps if not _is_education_gap_text(gap)]
        corrected.append(
            assessment.model_copy(
                update={
                    "matched": assessment.matched and not has_hard_violation,
                    "constraint_conclusions": conclusions,
                    "gaps": gaps,
                }
            )
        )
    return corrected


def _is_education_gap_text(text: str) -> bool:
    return any(
        term in text
        for term in ("学历", "教育背景", "专科", "大专", "本科", "学士", "硕士", "研究生", "博士")
    )


__all__ = ["DashScopeJobEvaluator"]
