import json
from pathlib import Path

from jobpicky.collection.parsers.job_51 import parse

FIXTURES = Path(__file__).parent / "fixtures"


def test_51job_parser_reads_public_detail_api() -> None:
    response = json.loads((FIXTURES / "job_51_detail.json").read_text())

    def request_json(url: str, _headers: object, _payload: object) -> object:
        assert url.endswith("job_detail.php")
        return response

    jobs = parse(
        "https://jobs.51job.com/nanjing/172953320.html",
        lambda _url: (_ for _ in ()).throw(AssertionError("detail should not fetch the page")),
        request_json,
    )

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "172953320"
    assert jobs[0]["title"] == "高校毕业生（15名）"
    assert jobs[0]["locations"] == ["南京"]
    assert jobs[0]["salary_min"] == 6000
    assert jobs[0]["salary_max"] == 7999


def test_51job_parser_reads_public_list_api() -> None:
    page = 'var params = {ctmid: "1234567", pagesize: 2000};'

    def request_json(url: str, _headers: object, payload: object) -> object:
        if url.endswith("job_list.php"):
            assert payload == {
                "ctmid": "1234567",
                "poscode": "",
                "jobarea": "",
                "pagesize": 2000,
                "sort": "joborder",
                "sequence": 1,
            }
            return {
                "status": "1",
                "resultbody": {
                    "totalnum": "1",
                    "joblist": [
                        {
                            "jobid": "172953320",
                            "jobname": "数据工程师",
                            "jobareaname": "北京",
                            "degreefrom": "硕士",
                        }
                    ],
                },
            }
        assert url.endswith("job_detail.php")
        assert payload == {"jobid": "172953320"}
        return {
            "status": "1",
            "resultbody": {
                "jobid": "172953320",
                "jobname": "数据工程师",
                "jobinfo": "负责数据平台建设。",
            },
        }

    jobs = parse(
        "https://campus.example/job.html",
        lambda _url: ("https://campus.example/job.html", page),
        request_json,
    )

    assert [job["title"] for job in jobs] == ["数据工程师"]
    assert jobs[0]["description"] == "负责数据平台建设。"
    assert jobs[0]["metadata"] == {"platform": "JOB_51", "record_kind": "job", "ctmid": "1234567"}


def test_51job_parser_reads_static_public_job_array() -> None:
    page = ("https://campus.example/job.html", (FIXTURES / "job_51_static.html").read_text())

    def request_json(_url: str, _headers: object, _payload: object) -> object:
        return {"status": "1", "resultbody": {"totalnum": "0", "joblist": []}}

    jobs = parse("https://campus.example/job.html", lambda _url: page, request_json)

    assert len(jobs) == 1
    assert jobs[0]["source_job_id"] == "172658922"
    assert jobs[0]["title"] == "数据分析实习生"
    assert jobs[0]["description"] == "参与数据分析项目。"
    assert jobs[0]["apply_url"] == (
        "https://xyz.51job.com/external/apply.aspx?jobid=172658922&ctmid=8753645"
    )
    assert jobs[0]["recruitment_type"] == "实习"
