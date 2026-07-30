from jobpicky.matching.embedding_text import truncate_embedding_text


def test_embedding_text_is_bounded_by_token_budget() -> None:
    text = truncate_embedding_text("中文" * 1000)

    assert text == ("中文" * 1000)[:512]


def test_embedding_text_keeps_complete_ascii_tokens() -> None:
    text = truncate_embedding_text("alpha beta gamma delta", max_tokens=2)

    assert text == "alpha beta"
