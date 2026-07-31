from jobpicky.collection.parsers.form import parse


def test_form_parser_keeps_public_recruitment_form_as_announcement() -> None:
    html = """
    <html><head><title>TCL 2026校园大使报名表</title></head>
    <body><main>校园招募报名信息收集。</main></body></html>
    """

    jobs = parse("https://forms.example.test/f/abc", lambda _url: html)

    assert jobs[0]["title"] == "TCL 2026校园大使报名表"
    assert jobs[0]["metadata"] == {
        "parser": "public_web",
        "record_kind": "public_announcement",
    }
    assert jobs[0]["apply_url"] is None
