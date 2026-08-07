import pytest

from jobpicky.config import Settings


def test_settings_read_and_normalize_environment() -> None:
    settings = Settings.from_env(
        {
            "JOBPICKY_APP_NAME": "AI JobPicky",
            "JOBPICKY_ENVIRONMENT": "test",
            "JOBPICKY_LOG_LEVEL": "debug",
        }
    )

    assert settings.app_name == "AI JobPicky"
    assert settings.environment == "test"
    assert settings.log_level == "DEBUG"


def test_settings_reject_unknown_log_level() -> None:
    with pytest.raises(ValueError, match="JOBPICKY_LOG_LEVEL"):
        Settings.from_env({"JOBPICKY_LOG_LEVEL": "verbose"})


def test_frontend_limits_and_credit_defaults_are_configured() -> None:
    settings = Settings.from_env({})

    assert settings.job_pool_default_page_size == 30
    assert settings.job_pool_public_page_size_max == 30
    assert settings.job_pool_authenticated_page_size_max == 100
    assert settings.recommendation_candidate_limit == 50
    assert settings.evaluation_workers == 2
    assert settings.signup_bonus_credits == 10_000
    assert settings.recommendation_cost == 100
    assert settings.access_token_ttl_seconds == 900
    assert settings.refresh_session_ttl_seconds == 2_592_000


def test_settings_read_evaluation_worker_limit() -> None:
    settings = Settings.from_env(
        {
            "JOBPICKY_EVALUATION_BATCH_SIZE": "5",
            "JOBPICKY_EVALUATION_WORKERS": "3",
        }
    )

    assert settings.evaluation_batch_size == 5
    assert settings.evaluation_workers == 3

    with pytest.raises(ValueError, match="EVALUATION_WORKERS"):
        Settings.from_env({"JOBPICKY_EVALUATION_WORKERS": "5"})


def test_settings_reject_insecure_production_jwt_and_wildcard_cors() -> None:
    with pytest.raises(ValueError, match="JWT_SIGNING_KEY"):
        Settings.from_env({"JOBPICKY_ENVIRONMENT": "production"})

    with pytest.raises(ValueError, match="must not contain"):
        Settings.from_env({"JOBPICKY_CORS_ALLOWED_ORIGINS": "*"})
