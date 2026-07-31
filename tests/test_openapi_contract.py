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
        "/api/v1/user/saved-jobs",
        "/api/v1/user/saved-jobs/{job_id}",
    }
    error_schema = schema["components"]["schemas"]["ErrorBody"]
    assert set(error_schema["required"]) >= {"code", "message", "request_id"}
    password_schema = schema["components"]["schemas"]["LoginRequest"]["properties"]["password"]
    assert password_schema["writeOnly"] is True
    assert "example" not in password_schema
