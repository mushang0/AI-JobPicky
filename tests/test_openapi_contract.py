from jobpicky.app import create_app
from jobpicky.config import Settings
from jobpicky.contracts import (
    AuthUserView,
    CurrentProfileView,
    ErrorBody,
    FilterOptionsLimits,
    FilterOptionsView,
    JobDetailView,
    JobListItem,
    JobListQuery,
    JobPoolPage,
    RecommendationAssessmentView,
    RecommendationCardView,
    RecommendationResultView,
    RecommendationRunAccepted,
    RecommendationRunRequest,
    RecommendationTaskView,
)

PUBLIC_CONTRACT_MODELS = (
    AuthUserView,
    CurrentProfileView,
    ErrorBody,
    FilterOptionsView,
    FilterOptionsLimits,
    JobDetailView,
    JobListItem,
    JobListQuery,
    JobPoolPage,
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
    assert set(schema["paths"]) == {"/api/v1/system/health"}
    error_schema = schema["components"]["schemas"]["ErrorBody"]
    assert set(error_schema["required"]) >= {"code", "message", "request_id"}
    assert "password" not in str(schema)
