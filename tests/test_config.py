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
