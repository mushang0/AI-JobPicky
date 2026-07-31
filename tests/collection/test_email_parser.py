import pytest

from jobpicky.collection.parsers.email import parse


def test_email_parser_fails_without_public_job_facts() -> None:
    with pytest.raises(ValueError, match="application method"):
        parse("hr@example.com")
