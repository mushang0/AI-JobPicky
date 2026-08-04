import json
from pathlib import Path
from typing import cast

import pytest

from jobpicky.collection.parsers.jqka import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_jqka_parser_reads_public_list_and_detail_api() -> None:
    list_response = json.loads((FIXTURES / "jqka_list.json").read_text())
    detail_response = json.loads((FIXTURES / "jqka_detail.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        if endpoint.endswith("/apply_list"):
            assert method == "GET"
            assert payload == {"page": 1, "pageCount": 50}
            return list_response
        assert endpoint.endswith("/apply_detail?id=1001")
        assert method == "GET"
        assert payload is None
        return detail_response

    jobs = parse("http://campus.10jqka.com.cn/mobile/job/list", request, max_workers=1)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "1001"
    assert jobs[0]["description"] == "参与数据平台建设与维护。\n熟悉一种主流编程语言。"
    assert jobs[0]["detail_url"] == ("http://campus.10jqka.com.cn/mobile/job/detail?id=1001")
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "10jqka-campus"
    assert metadata["list_count"] == 1


def test_jqka_parser_rejects_incomplete_pagination() -> None:
    responses = iter(
        [
            {
                "erro_code": "0",
                "ex_data": {"total": 2, "apply_show_do_list": [{"id": 1}]},
            },
            {"erro_code": "0", "ex_data": {"total": 2, "apply_show_do_list": []}},
        ]
    )

    with pytest.raises(ValueError, match="incomplete page"):
        parse(
            "http://campus.10jqka.com.cn/mobile/job/list",
            lambda _endpoint, _method, _payload: next(responses),
            max_workers=1,
        )
