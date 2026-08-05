from jobpicky.infrastructure.profile_resources import load_profile_import_prompt


def test_profile_import_prompt_is_loaded_from_an_external_resource() -> None:
    prompt = load_profile_import_prompt()

    assert "target_locations" in prompt
    assert "languages" in prompt
    assert "输出格式示例" in prompt
