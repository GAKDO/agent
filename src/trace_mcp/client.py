"""게이트웨이 호출. 액세스 JWT가 만료(401)되면 저장된 리프레시 토큰으로 한 번 재발급받고 다시 부른다."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

from trace_mcp import session as sess

REFRESH_COOKIE = "trace_refresh"  # contracts auth-server: HttpOnly 쿠키 이름
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass
class Response:
    status: int
    body: Any
    set_cookies: list[str] = field(default_factory=list)


Http = Callable[[str, str, dict[str, str], bytes | None], Response]


class ApiError(Exception):
    def __init__(self, status: int, code: str, title: str = "") -> None:
        super().__init__(f"HTTP {status} {code}" + (f": {title}" if title else ""))
        self.status, self.code, self.title = status, code, title


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """리디렉션을 따라가지 않는다. urllib은 Authorization·Cookie를 다른 주소로도 그대로 넘기기 때문이다."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def http_request(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Response:
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with _OPENER.open(req, timeout=30) as resp:
            raw, status, hdrs = resp.read(), resp.status, resp.headers
    except urllib.error.HTTPError as err:
        raw, status, hdrs = err.read(), err.code, err.headers
    except OSError as err:  # URLError·TimeoutError·연결 끊김
        raise ApiError(503, "NETWORK_ERROR", "게이트웨이에 연결하지 못했습니다") from err
    try:
        body = json.loads(raw) if raw else None
    except ValueError:
        body = None
    return Response(status, body, hdrs.get_all("Set-Cookie") or [])


def api_url() -> str:
    return os.environ.get("TRACE_API_URL", "https://gakdo.site/")


def insecure(base: str) -> bool:
    url = urllib.parse.urlparse(base)
    return url.scheme != "https" and (url.hostname or "") not in _LOCAL_HOSTS


def refresh_from(cookies: list[str]) -> str | None:
    for header in cookies:
        jar = SimpleCookie()
        jar.load(header)
        if REFRESH_COOKIE in jar:
            return jar[REFRESH_COOKIE].value
    return None


def _error(resp: Response) -> ApiError:
    body = resp.body if isinstance(resp.body, dict) else {}
    return ApiError(resp.status, str(body.get("code", "HTTP_ERROR")), str(body.get("title", "")))


class TraceClient:
    def __init__(self, base: str | None = None, path: Path | None = None, http: Http = http_request) -> None:
        self.base = (base or api_url()).rstrip("/") + "/api/v1"
        self.path = path or sess.default_path()
        self.http = http
        if insecure(self.base):
            raise ValueError("토큰이 평문으로 나갑니다. TRACE_API_URL은 https여야 합니다(localhost 제외).")

    def _call(self, method: str, path: str, headers: dict[str, str], body: dict[str, Any] | None = None) -> Response:
        data = json.dumps(body).encode() if body is not None else None
        hdrs = {"Accept": "application/json", **headers}
        if data is not None:
            hdrs["Content-Type"] = "application/json"
        return self.http(method, self.base + path, hdrs, data)

    def login(self, email: str, password: str) -> str:
        """로그인해 세션 파일에 저장하고 역할(CUSTOMER·ADMIN)을 돌려준다."""
        resp = self._call("POST", "/auth/login", {}, {"email": email, "password": password})
        if resp.status != 200 or not isinstance(resp.body, dict):
            raise _error(resp)
        sess.save(self.path, sess.Session(resp.body["accessToken"], refresh_from(resp.set_cookies)))
        return str(resp.body.get("role", ""))

    def logout(self) -> None:
        current = sess.load(self.path)
        try:
            if current:
                self._call("POST", "/auth/logout", {"Authorization": f"Bearer {current.access_token}"})
        finally:
            sess.clear(self.path)  # 서버 호출이 실패해도 로컬 토큰은 지운다

    def _refresh(self, current: sess.Session) -> sess.Session | None:
        if not current.refresh_token:
            return None
        resp = self._call("POST", "/auth/refresh", {"Cookie": f"{REFRESH_COOKIE}={current.refresh_token}"})
        if resp.status in (401, 403):
            return None  # 리프레시 토큰 거부: 다시 로그인해야 한다
        if resp.status != 200 or not isinstance(resp.body, dict):
            raise _error(resp)  # 일시 오류는 만료로 취급하지 않는다
        new = sess.Session(resp.body["accessToken"], refresh_from(resp.set_cookies) or current.refresh_token)
        sess.save(self.path, new)
        return new

    def get(self, path: str, query: dict[str, str] | None = None) -> Any:
        current = sess.load(self.path)
        if current is None:
            raise ApiError(401, "NOT_LOGGED_IN", "터미널에서 `trace-mcp login`으로 먼저 로그인해 주세요")
        if query:
            path += "?" + urllib.parse.urlencode(query)
        resp = self._call("GET", path, {"Authorization": f"Bearer {current.access_token}"})
        if resp.status == 401 and (new := self._refresh(current)):
            resp = self._call("GET", path, {"Authorization": f"Bearer {new.access_token}"})
        if resp.status == 401:
            raise ApiError(401, "LOGIN_EXPIRED", "로그인이 만료됐습니다. `trace-mcp login`으로 다시 로그인해 주세요")
        if resp.status != 200:
            raise _error(resp)
        return resp.body
