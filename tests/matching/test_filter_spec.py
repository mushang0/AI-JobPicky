from jobpicky.matching import BaselineMatchingService
from matching.factories import make_profile


def test_maps_profile_fields_to_filter_spec() -> None:
    profile = make_profile(
        target_locations=["上海", "杭州"],
        excluded_roles=["销售"],
        education="硕士",
        graduation_year=2026,
        expected_salary_min=25000,
    )

    spec = BaselineMatchingService().build_filter_spec(profile, None)

    assert spec.target_locations == ["上海", "杭州"]
    assert spec.excluded_roles == ["销售"]
    assert spec.education == "硕士"
    assert spec.graduation_year == 2026
    assert spec.min_salary == 25000


def test_empty_profile_fields_mean_no_restriction() -> None:
    profile = make_profile(
        target_locations=[],
        excluded_roles=[],
        education=None,
        graduation_year=None,
        expected_salary_min=None,
    )

    spec = BaselineMatchingService().build_filter_spec(profile, None)

    assert spec.target_locations == []
    assert spec.excluded_roles == []
    assert spec.education is None
    assert spec.graduation_year is None
    assert spec.min_salary is None


def test_recruitment_type_is_never_inferred_and_only_open_is_default() -> None:
    spec = BaselineMatchingService().build_filter_spec(make_profile(), None)

    assert spec.recruitment_types == []
    assert spec.only_open is True


def test_profile_recruitment_types_become_deterministic_hard_filters() -> None:
    spec = BaselineMatchingService().build_filter_spec(
        make_profile(recruitment_types=["社招"]),
        None,
    )

    assert spec.recruitment_types == ["社招"]


def test_extra_request_does_not_affect_filter_spec() -> None:
    service = BaselineMatchingService()
    profile = make_profile()

    without_extra = service.build_filter_spec(profile, None)
    with_extra = service.build_filter_spec(profile, "只考虑远程岗位")

    assert with_extra == without_extra
