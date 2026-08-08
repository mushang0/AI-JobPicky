import json
from pathlib import Path
from typing import cast

from jobpicky.collection.parsers.huawei import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_huawei_parser_reads_public_list_with_real_jd_fields() -> None:
    list_response = json.loads((FIXTURES / "huawei_list.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        assert endpoint.endswith("/getJob/newHr/page/30/1")
        assert method == "GET"
        assert payload == {"language": "zh_CN"}
        return list_response

    jobs = parse(
        "https://career.huawei.com/reccampportal/portal5/campus-recruitment.html",
        request,
        max_workers=1,
    )

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "24130"
    assert jobs[0]["title"] == "计划及调度工程师"
    assert (
        jobs[0]["description"] == "负责项目计划与资源协同。\n本科及以上学历，具备良好的沟通能力。"
    )
    assert jobs[0]["locations"] == ["Shenzhen", "Dongguan"]
    assert jobs[0]["education_requirement"] == "本科"
    assert jobs[0]["detail_url"] == (
        "https://career.huawei.com/reccampportal/portal5/"
        "campus-recruitment-detail.html?jobId=24130&dataSource=1"
    )
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["platform_family"] == "huawei-careers"
    assert metadata["detail_status"] == "list_api"
    assert metadata["list_count"] == 1


def test_huawei_parser_fetches_detail_when_list_has_no_jd() -> None:
    list_response = {
        "pageVO": {"totalRows": 1, "curPage": 1, "pageSize": 30, "totalPages": 1},
        "result": [{"jobId": "24130", "jobname": "计划及调度工程师", "dataSource": "1"}],
    }
    detail_response = json.loads((FIXTURES / "huawei_detail.json").read_text())

    def request(endpoint: str, method: str, payload: object) -> object:
        if endpoint.endswith("/page/30/1"):
            assert method == "GET"
            return list_response
        assert endpoint.endswith("/getJobDetail/newHr")
        assert method == "GET"
        assert payload == {"jobId": "24130", "dataSource": "1"}
        return detail_response

    jobs = parse(
        "https://career.huawei.com/reccampportal/portal5/campus-recruitment.html",
        request,
        max_workers=1,
    )

    assert jobs[0]["description"] == (
        "负责项目计划、交付节奏与资源协同。\n"
        "本科及以上学历，具备良好的沟通能力和数据分析能力。\n"
        "参与跨团队项目运营与流程优化。"
    )
    assert jobs[0]["locations"] == ["深圳"]
    metadata = cast(dict[str, object], jobs[0]["metadata"])
    assert metadata["detail_status"] == "public_api"


def test_huawei_parser_fetches_direct_detail() -> None:
    detail_response = json.loads((FIXTURES / "huawei_detail.json").read_text())
    calls: list[tuple[str, str, object]] = []

    def request(endpoint: str, method: str, payload: object) -> object:
        calls.append((endpoint, method, payload))
        assert endpoint.endswith("/getJobDetail/newHr")
        assert method == "GET"
        assert payload == {"jobId": "24130", "dataSource": "1"}
        return detail_response

    jobs = parse(
        "https://career.huawei.com/reccampportal/portal5/campus-recruitment-detail.html?"
        "jobId=24130&dataSource=1",
        request,
    )

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "24130"
    assert calls == [
        (
            "https://career.huawei.com/reccampportal/services/portal/portalpub/getJobDetail/newHr",
            "GET",
            {"jobId": "24130", "dataSource": "1"},
        )
    ]
