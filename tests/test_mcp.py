"""trace-mcp: 가짜 게이트웨이로 로그인·재발급·도구를 검사한다(네트워크 없음)."""

from __future__ import annotations

import asyncio
import os
import stat
from pathlib import Path

import pytest

from trace_mcp import session as sess
from trace_mcp import tools
from trace_mcp.client import ApiError, Response, TraceClient

RENTAL = {
    "rentalId": "R1", "status": "OPEN",
    "checkpoints": [
        {"checkpointId": "C-OUT", "type": "OUT", "status": "SEALED", "occurredAt": "2026-11-12T09:00:00+09:00"},
        {"checkpointId": "C-RCV", "type": "RCV", "status": "OPEN", "occurredAt": None},
    ],
}


class FakeGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str]]] = []
        self.valid = "access-1"

    def __call__(self, method: str, url: str, headers: dict[str, str], data: bytes | None) -> Response:
        path = url.split("/api/v1", 1)[1]
        self.calls.append((method, path, headers))
        if path == "/auth/login":
            return Response(200, {"accessToken": "access-1", "role": "CUSTOMER"},
                            ["trace_refresh=refresh-1; HttpOnly; Secure; Path=/api/v1/auth"])
        if path == "/auth/refresh":
            if headers.get("Cookie") != "trace_refresh=refresh-1":
                return Response(401, {"code": "REFRESH_INVALID"})
            self.valid = "access-2"
            return Response(200, {"accessToken": "access-2"}, ["trace_refresh=refresh-2; HttpOnly"])
        if headers.get("Authorization") != f"Bearer {self.valid}":
            return Response(401, {"code": "UNAUTHORIZED"})
        if path == "/rentals/R1":
            return Response(200, RENTAL)
        if path == "/captures/checkpoints/C-OUT/inspection":
            return Response(200, {"grade": "A", "scratches": []})
        if path == "/diagnostics/checkpoints/C-OUT":
            return Response(404, {"code": "NOT_FOUND", "title": "진단 없음"})
        if path.startswith("/rentals"):
            return Response(200, {"items": [{"rentalId": "R1"}], "path": path})
        return Response(404, {"code": "NOT_FOUND"})


@pytest.fixture
def gw() -> FakeGateway:
    return FakeGateway()


@pytest.fixture
def client(tmp_path: Path, gw: FakeGateway) -> TraceClient:
    return TraceClient("https://gakdo.example/", tmp_path / "s" / "session.json", gw)


def test_로그인하면_세션을_600_파일에_저장한다(client: TraceClient) -> None:
    assert client.login("me@example.com", "pw") == "CUSTOMER"
    saved = sess.load(client.path)
    assert saved == sess.Session("access-1", "refresh-1")
    if os.name == "posix":  # Windows에는 유닉스 권한 비트가 없다(사용자 프로필 폴더 ACL에 기댄다)
        assert stat.S_IMODE(client.path.stat().st_mode) == 0o600


def test_로그인_전에는_안내_오류를_낸다(client: TraceClient) -> None:
    with pytest.raises(ApiError) as err:
        tools.whoami(client)
    assert err.value.code == "NOT_LOGGED_IN"


def test_액세스_토큰이_만료되면_리프레시로_한_번_재발급한다(client: TraceClient, gw: FakeGateway) -> None:
    client.login("me@example.com", "pw")
    gw.valid = "access-2"
    assert tools.get_rental(client, "R1")["rentalId"] == "R1"
    assert sess.load(client.path) == sess.Session("access-2", "refresh-2")


def test_리프레시도_실패하면_다시_로그인하라고_한다(client: TraceClient) -> None:
    sess.save(client.path, sess.Session("old", "bad"))
    with pytest.raises(ApiError) as err:
        tools.list_my_rentals(client)
    assert err.value.code == "LOGIN_EXPIRED"


def test_상태로_렌탈을_거르고_경로_조각은_인코딩한다(client: TraceClient, gw: FakeGateway) -> None:
    client.login("me@example.com", "pw")
    assert tools.list_my_rentals(client, "OPEN")["path"] == "/rentals?status=OPEN"
    tools.get_rental(client, "../auth/me")
    assert gw.calls[-1][1] == "/rentals/..%2Fauth%2Fme"


def test_요약은_촬영이_끝난_시점만_결과를_붙이고_없는_결과는_사유로_남긴다(client: TraceClient) -> None:
    client.login("me@example.com", "pw")
    out = tools.summarize_rental(client, "R1")
    first, second = out["checkpoints"]
    assert first["name"] == "출고"
    assert first["inspection"] == {"result": {"grade": "A", "scratches": []}}
    assert first["diagnostics"] == {"result": None, "reason": "NOT_FOUND"}
    assert second["name"] == "수령" and "inspection" not in second


def test_https가_아닌_주소는_거부한다(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        TraceClient("http://gakdo.example/", tmp_path / "s.json")
    TraceClient("http://localhost:8080/", tmp_path / "s.json")


def test_MCP_서버는_읽기_전용_도구_7개를_노출한다(client: TraceClient) -> None:
    server = pytest.importorskip("trace_mcp.server")
    app = server.build(client)
    listed = asyncio.run(app.list_tools())
    names = {t.name for t in listed}
    assert names == {"whoami", "list_my_rentals", "get_rental", "get_inspection",
                     "get_diagnostics", "get_device_model", "summarize_rental"}
    assert all(t.annotations and t.annotations.read_only_hint for t in listed)


def test_리프레시가_일시_오류면_만료가_아니라_그_오류를_알린다(client: TraceClient, gw: FakeGateway) -> None:
    sess.save(client.path, sess.Session("old", "refresh-1"))
    real = gw.__call__

    def flaky(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Response:
        if url.endswith("/auth/refresh"):
            return Response(503, {"code": "UNAVAILABLE"})
        return real(method, url, headers, data)

    client.http = flaky
    with pytest.raises(ApiError) as err:
        tools.list_my_rentals(client)
    assert err.value.code == "UNAVAILABLE"


def test_로그아웃은_서버_호출이_실패해도_로컬_세션을_지운다(client: TraceClient) -> None:
    sess.save(client.path, sess.Session("a", "r"))

    def down(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Response:
        raise ApiError(503, "NETWORK_ERROR")

    client.http = down
    with pytest.raises(ApiError):
        client.logout()
    assert not client.path.exists()
