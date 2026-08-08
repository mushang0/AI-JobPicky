import json
from urllib.request import Request

from jobpicky.collection.parsers import public_api


class _Response:
    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, _limit: int) -> bytes:
        return json.dumps({"ok": True}).encode()


def test_request_json_merges_public_headers(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def urlopen(request: Request, timeout: int) -> _Response:
        captured["request"] = request
        captured["timeout"] = timeout
        return _Response()

    monkeypatch.setattr(public_api, "urlopen", urlopen)

    response = public_api.request_json(
        "https://jobs.example.test/api/list",
        "https://jobs.example.test/campus/positions",
        "GET",
        None,
        headers={"X-AppKey": "public-app-key"},
    )

    request = captured["request"]
    assert response == {"ok": True}
    assert captured["timeout"] == 20
    assert isinstance(request, Request)
    request_headers = {key.casefold(): value for key, value in request.header_items()}
    assert request_headers["x-appkey"] == "public-app-key"
