import stat
import threading
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from jobpicky.infrastructure.feishu_auth import (
    FeishuOAuthClient,
    FeishuTokenStore,
    TokenBundle,
    wait_for_local_authorization_code,
)


def test_authorization_url_contains_oauth_parameters() -> None:
    client = FeishuOAuthClient(
        "app-id",
        "app-secret",
        redirect_uri="http://localhost:8787/callback",
    )

    query = parse_qs(
        urlsplit(client.authorization_url(state="state-1", scopes="scope-a scope-b")).query
    )

    assert query["client_id"] == ["app-id"]
    assert query["redirect_uri"] == ["http://localhost:8787/callback"]
    assert query["scope"] == ["scope-a scope-b"]
    assert query["state"] == ["state-1"]


def test_token_store_is_owner_only_and_round_trips(tmp_path) -> None:
    path = tmp_path / "feishu-token.json"
    bundle = TokenBundle("access-value", 2_000, "refresh-value", 3_000)
    store = FeishuTokenStore(path)

    store.save(bundle)

    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert store.load() == bundle


def test_callback_listener_is_started_before_browser_callback() -> None:
    server_url: str | None = None
    callback_thread: threading.Thread | None = None

    def open_browser_after_listener_is_ready() -> None:
        nonlocal callback_thread, server_url
        assert server_url is not None

        def send_callback() -> None:
            with urlopen(f"{server_url}?code=one-time-code&state=expected", timeout=3) as response:
                response.read()

        callback_thread = threading.Thread(target=send_callback, daemon=True)
        callback_thread.start()

    # Port 0 lets the OS choose a free port, but the redirect URI must contain
    # the actual port. Use a short-lived local socket to reserve one for setup.
    import socket

    with socket.socket() as socket_:
        socket_.bind(("127.0.0.1", 0))
        port = socket_.getsockname()[1]
    server_url = f"http://127.0.0.1:{port}/callback"

    code = wait_for_local_authorization_code(
        server_url,
        expected_state="expected",
        timeout_seconds=5,
        on_ready=open_browser_after_listener_is_ready,
    )

    if callback_thread is not None:
        callback_thread.join(timeout=3)
    assert code == "one-time-code"
