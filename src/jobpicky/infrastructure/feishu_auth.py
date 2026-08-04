"""Feishu OAuth helpers and atomic token storage."""

from __future__ import annotations

import json
import os
import tempfile
import time
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

_TOKEN_URL = "https://open.feishu.cn/open-apis/authen/v2/oauth/token"
_AUTHORIZATION_URL = "https://accounts.feishu.cn/open-apis/authen/v1/authorize"
_DEFAULT_TIMEOUT_SECONDS = 20
_TOKEN_REFRESH_MARGIN_SECONDS = 60


class FeishuAuthError(RuntimeError):
    """Raised when OAuth or token persistence cannot complete safely."""


@dataclass(frozen=True, slots=True)
class TokenBundle:
    access_token: str
    access_expires_at: float
    refresh_token: str
    refresh_expires_at: float | None

    @classmethod
    def from_response(
        cls,
        response: dict[str, object],
        *,
        previous_refresh_token: str | None = None,
    ) -> TokenBundle:
        access_token = response.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise FeishuAuthError("Feishu token response did not contain access_token")

        refresh_token = response.get("refresh_token") or previous_refresh_token
        if not isinstance(refresh_token, str) or not refresh_token:
            raise FeishuAuthError(
                "Feishu token response did not contain refresh_token; keep offline_access enabled"
            )

        expires_in = _positive_number(response.get("expires_in"), "expires_in")
        refresh_expires_in = _optional_positive_number(
            response.get("refresh_token_expires_in"), "refresh_token_expires_in"
        )
        now = time.time()
        return cls(
            access_token=access_token,
            access_expires_at=now + expires_in,
            refresh_token=refresh_token,
            refresh_expires_at=(now + refresh_expires_in if refresh_expires_in else None),
        )

    @classmethod
    def from_file_data(cls, data: object) -> TokenBundle:
        if not isinstance(data, dict):
            raise FeishuAuthError("Feishu token file must contain a JSON object")
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        access_expires_at = data.get("access_expires_at")
        refresh_expires_at = data.get("refresh_expires_at")
        if not isinstance(access_token, str) or not access_token:
            raise FeishuAuthError("Feishu token file has no access_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise FeishuAuthError("Feishu token file has no refresh_token")
        if not isinstance(access_expires_at, (int, float)):
            raise FeishuAuthError("Feishu token file has invalid access_expires_at")
        if refresh_expires_at is not None and not isinstance(refresh_expires_at, (int, float)):
            raise FeishuAuthError("Feishu token file has invalid refresh_expires_at")
        return cls(
            access_token=access_token,
            access_expires_at=float(access_expires_at),
            refresh_token=refresh_token,
            refresh_expires_at=(
                float(refresh_expires_at) if refresh_expires_at is not None else None
            ),
        )

    def as_file_data(self) -> dict[str, object]:
        return {
            "access_token": self.access_token,
            "access_expires_at": self.access_expires_at,
            "refresh_token": self.refresh_token,
            "refresh_expires_at": self.refresh_expires_at,
        }

    def access_token_is_valid(self) -> bool:
        return self.access_expires_at > time.time() + _TOKEN_REFRESH_MARGIN_SECONDS


class FeishuTokenStore:
    """Persist the rotating token pair without exposing it in logs or arguments."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser()

    def load(self) -> TokenBundle:
        if not self.path.is_file():
            raise FeishuAuthError(f"Feishu token file does not exist: {self.path}")
        if self.path.stat().st_mode & 0o077:
            raise FeishuAuthError(
                f"Feishu token file must be readable only by its owner: {self.path}"
            )
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise FeishuAuthError(f"cannot read Feishu token file: {self.path}") from exc
        return TokenBundle.from_file_data(data)

    def save(self, bundle: TokenBundle) -> None:
        parent = self.path.parent
        try:
            parent.mkdir(parents=True, exist_ok=True)
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                dir=parent,
                text=True,
            )
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                json.dump(bundle.as_file_data(), file, ensure_ascii=False, sort_keys=True)
                file.write("\n")
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary_name, self.path)
            os.chmod(self.path, 0o600)
        except OSError as exc:
            raise FeishuAuthError(f"cannot save Feishu token file: {self.path}") from exc
        finally:
            if "temporary_name" in locals() and os.path.exists(temporary_name):
                os.unlink(temporary_name)


class FeishuOAuthClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        *,
        redirect_uri: str,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not client_id.strip() or not client_secret.strip():
            raise ValueError("Feishu client_id and client_secret are required")
        if not redirect_uri.strip():
            raise ValueError("Feishu redirect_uri is required")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._timeout_seconds = timeout_seconds

    @property
    def redirect_uri(self) -> str:
        return self._redirect_uri

    def authorization_url(self, *, state: str, scopes: str) -> str:
        query = urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "scope": scopes,
                "state": state,
            }
        )
        return f"{_AUTHORIZATION_URL}?{query}"

    def exchange_code(self, code: str) -> TokenBundle:
        if not code.strip():
            raise ValueError("Feishu authorization code is required")
        response = self._post(
            {
                "grant_type": "authorization_code",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "redirect_uri": self._redirect_uri,
            }
        )
        return TokenBundle.from_response(response)

    def refresh(self, refresh_token: str) -> TokenBundle:
        response = self._post(
            {
                "grant_type": "refresh_token",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "refresh_token": refresh_token,
            }
        )
        return TokenBundle.from_response(response, previous_refresh_token=refresh_token)

    def _post(self, payload: dict[str, str]) -> dict[str, object]:
        request = Request(
            _TOKEN_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self._timeout_seconds) as response:  # noqa: S310
                raw = response.read()
        except HTTPError as exc:
            raise FeishuAuthError(f"Feishu token request failed with HTTP {exc.code}") from exc
        except URLError as exc:
            raise FeishuAuthError("Feishu token request could not reach the API") from exc
        try:
            decoded = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise FeishuAuthError("Feishu token API returned invalid JSON") from exc
        if not isinstance(decoded, dict):
            raise FeishuAuthError("Feishu token API returned an invalid response")
        if decoded.get("code") != 0:
            message = decoded.get("msg") or decoded.get("error_description") or "unknown error"
            raise FeishuAuthError(f"Feishu token request rejected: {message}")
        return decoded


class FeishuTokenManager:
    def __init__(self, oauth: FeishuOAuthClient, store: FeishuTokenStore) -> None:
        self._oauth = oauth
        self._store = store

    def exchange_and_save(self, code: str) -> TokenBundle:
        bundle = self._oauth.exchange_code(code)
        self._store.save(bundle)
        return bundle

    def get_access_token(self, *, force_refresh: bool = False) -> str:
        bundle = self._store.load()
        if not force_refresh and bundle.access_token_is_valid():
            return bundle.access_token
        refreshed = self._oauth.refresh(bundle.refresh_token)
        self._store.save(refreshed)
        return refreshed.access_token


def wait_for_local_authorization_code(
    redirect_uri: str,
    *,
    expected_state: str,
    timeout_seconds: int = 180,
    on_ready: Callable[[], None] | None = None,
) -> str:
    parts = urlsplit(redirect_uri)
    if parts.scheme != "http" or parts.hostname not in {"localhost", "127.0.0.1"}:
        raise FeishuAuthError("local OAuth callback must use http://localhost or http://127.0.0.1")
    if parts.port is None or not parts.path:
        raise FeishuAuthError("local OAuth callback must include a port and path")

    result: dict[str, str] = {}

    class CallbackHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - required HTTP handler name
            request_parts = urlsplit(self.path)
            if request_parts.path != parts.path:
                self.send_error(404)
                return
            query = parse_qs(request_parts.query)
            if query.get("error"):
                result["error"] = query["error"][0]
            elif query.get("code"):
                result["code"] = query["code"][0]
                result["state"] = query.get("state", [""])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<html><body><p>授权完成，可以关闭此页面。</p></body></html>".encode())

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", parts.port), CallbackHandler)
    server.timeout = 0.5
    deadline = time.monotonic() + timeout_seconds
    try:
        if on_ready is not None:
            on_ready()
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()

    if not result:
        raise FeishuAuthError("timed out waiting for Feishu OAuth callback")
    if result.get("error"):
        raise FeishuAuthError(f"Feishu OAuth was rejected: {result['error']}")
    if result.get("state") != expected_state:
        raise FeishuAuthError("Feishu OAuth state did not match")
    code = result.get("code")
    if not code:
        raise FeishuAuthError("Feishu OAuth callback did not contain an authorization code")
    return code


def open_authorization_url(url: str) -> None:
    if not webbrowser.open(url):
        print(f"请在浏览器打开此地址：{url}")


def _positive_number(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise FeishuAuthError(f"Feishu token response has invalid {name}")
    return float(value)


def _optional_positive_number(value: object, name: str) -> float | None:
    if value is None:
        return None
    return _positive_number(value, name)


__all__ = [
    "FeishuAuthError",
    "FeishuOAuthClient",
    "FeishuTokenManager",
    "FeishuTokenStore",
    "TokenBundle",
    "open_authorization_url",
    "wait_for_local_authorization_code",
]
