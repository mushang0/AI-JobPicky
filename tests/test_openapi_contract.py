from jobpicky.app import create_app
from jobpicky.config import Settings
from jobpicky.contracts import (
    AccessTokenResponse,
    AuthUserView,
    CreditSummary,
    CurrentProfileView,
    ErrorBody,
    FilterOptionsLimits,
    FilterOptionsView,
    JobDetailView,
    JobFilterSource,
    JobListItem,
    JobListQuery,
    JobPoolPage,
    LoginRequest,
    LoginResponse,
    RecommendationAssessmentView,
    RecommendationCardView,
    RecommendationResultView,
    RecommendationRunAccepted,
    RecommendationRunRequest,
    RecommendationTaskView,
)

PUBLIC_CONTRACT_MODELS = (
    AccessTokenResponse,
    AuthUserView,
    CreditSummary,
    CurrentProfileView,
    ErrorBody,
    FilterOptionsView,
    FilterOptionsLimits,
    JobFilterSource,
    JobDetailView,
    JobListItem,
    JobListQuery,
    JobPoolPage,
    LoginRequest,
    LoginResponse,
    RecommendationAssessmentView,
    RecommendationCardView,
    RecommendationResultView,
    RecommendationRunAccepted,
    RecommendationRunRequest,
    RecommendationTaskView,
)


def test_public_contract_models_generate_closed_object_schemas() -> None:
    for model in PUBLIC_CONTRACT_MODELS:
        schema = model.model_json_schema()
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert schema["properties"]


def test_openapi_lists_only_real_routes_until_business_handlers_exist() -> None:
    schema = create_app(Settings(environment="test")).openapi()
    assert set(schema["paths"]) == {
        "/api/v1/auth/login",
        "/api/v1/auth/logout",
        "/api/v1/auth/me",
        "/api/v1/auth/refresh",
        "/api/v1/auth/register",
        "/api/v1/jobs",
        "/api/v1/jobs/filter-options",
        "/api/v1/jobs/{job_id}",
        "/api/v1/system/health",
        "/api/v1/user/credits",
        "/api/v1/user/profiles/current",
        "/api/v1/user/recommendation-runs",
        "/api/v1/user/recommendation-runs/{run_id}",
        "/api/v1/user/recommendation-runs/{run_id}/results",
        "/api/v1/user/recommendations",
        "/api/v1/user/recommendations/{recommendation_id}",
        "/api/v1/user/recommendations/{recommendation_id}/feedback",
        "/api/v1/user/saved-jobs",
        "/api/v1/user/saved-jobs/{job_id}",
    }
    error_schema = schema["components"]["schemas"]["ErrorBody"]
    assert set(error_schema["required"]) >= {"code", "message", "request_id"}
    password_schema = schema["components"]["schemas"]["LoginRequest"]["properties"]["password"]
    assert password_schema["writeOnly"] is True
    assert "example" not in password_schema


def test_jobs_query_is_expressed_as_repeated_query_parameters() -> None:
    schema = create_app(Settings(environment="test")).openapi()
    operation = schema["paths"]["/api/v1/jobs"]["get"]
    assert "requestBody" not in operation

    parameters = {parameter["name"]: parameter for parameter in operation["parameters"]}
    for name in (
        "city",
        "company_nature",
        "source_id",
        "recruitment_type",
        "education",
        "graduation_year",
    ):
        assert parameters[name]["in"] == "query"
        variants = parameters[name]["schema"].get("anyOf", [parameters[name]["schema"]])
        array_schema = next(variant for variant in variants if variant.get("type") == "array")
        assert array_schema["maxItems"] == 50

    q_schema = parameters["q"]["schema"]
    assert any(variant.get("maxLength") == 200 for variant in q_schema["anyOf"])
    assert parameters["page"]["schema"]["minimum"] == 1
    assert parameters["page_size"]["schema"] == {
        "type": "integer",
        "maximum": 100,
        "minimum": 1,
        "default": 30,
        "title": "Page Size",
    }
