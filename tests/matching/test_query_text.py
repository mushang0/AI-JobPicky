from factories import make_profile

from jobpicky.matching import BaselineMatchingService


def test_composes_query_text_in_fixed_order() -> None:
    profile = make_profile(
        target_roles=["后端工程师", "平台工程师"],
        skills=["Python", "PostgreSQL"],
        experience_summary="三年后端开发经验",
    )

    text = BaselineMatchingService().build_query_text(profile, "希望接触云原生")

    assert text == ("后端工程师\n平台工程师\nPython\nPostgreSQL\n三年后端开发经验\n希望接触云原生")


def test_deduplicates_and_ignores_blank_parts() -> None:
    # Contract-level NonEmptyStr already guarantees non-blank profile fields;
    # the only blank input that can reach the service is effective_extra_request.
    profile = make_profile(target_roles=["Python"], skills=["Python"], experience_summary=None)

    text = BaselineMatchingService().build_query_text(profile, "  ")

    assert text == "Python"


def test_empty_profile_produces_empty_query_text() -> None:
    profile = make_profile(
        target_roles=[],
        skills=[],
        experience_summary=None,
        extra_request=None,
    )

    assert BaselineMatchingService().build_query_text(profile, None) == ""


def test_query_text_is_reproducible() -> None:
    service = BaselineMatchingService()
    profile = make_profile()

    assert service.build_query_text(profile, "补充要求") == service.build_query_text(
        profile, "补充要求"
    )
