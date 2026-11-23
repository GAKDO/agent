# 이 파일이 확인하는 것: 사용자용 MCP 서버 trace-mcp(11/10 추가).
# 고객이 자기 컴퓨터의 Claude 같은 AI 앱에 연결해 "내 렌탈 검사 결과 알려줘"처럼 물을 수 있게 하는 도구다.
# 로그인·토큰 재발급·세션 파일 보관·읽기 전용 도구들을 가짜 gateway로 시험한다(네트워크 없음).
# 테스트의 비밀번호 "pw"·토큰 "access-1" 등은 진짜 값이 아닌 임의 글자다.

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

# 가짜 렌탈 R1: 출고(OUT) 시점은 봉인 끝, 수령(RCV) 시점은 아직 열림.
RENTAL = {
    "rentalId": "R1", "status": "OPEN",
    "checkpoints": [
        {"checkpointId": "C-OUT", "type": "OUT", "status": "SEALED", "occurredAt": "2026-11-12T09:00:00+09:00"},
        {"checkpointId": "C-RCV", "type": "RCV", "status": "OPEN", "occurredAt": None},
    ],
}


# 가짜 TRACE gateway. 로그인하면 토큰을 주고, 리프레시 쿠키가 맞으면 새 토큰으로 바꿔 준다.
# 토큰이 맞으면 렌탈·검사 결과를 주고, 출고 진단은 "없음(404)"으로 답한다.
# ※ 응답 코드: 404 = 찾을 수 없음(없는 주소나 데이터)
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


# 테스트용 MCP 클라이언트. 세션 파일은 테스트 임시 폴더에 둔다.
@pytest.fixture
def client(tmp_path: Path, gw: FakeGateway) -> TraceClient:
    return TraceClient("https://gakdo.example/", tmp_path / "s" / "session.json", gw)


# [상황] 고객이 이메일·비밀번호로 로그인한다.
# [기대] 역할 CUSTOMER를 돌려주고 토큰을 세션 파일에 저장한다. 파일 권한은 본인만 읽는 600(맥·리눅스).
def test_로그인하면_세션을_600_파일에_저장한다(client: TraceClient) -> None:
    assert client.login("me@example.com", "pw") == "CUSTOMER"
    saved = sess.load(client.path)
    assert saved == sess.Session("access-1", "refresh-1")
    if os.name == "posix":  # Windows에는 유닉스 권한 비트가 없다(사용자 프로필 폴더 ACL에 기댄다)
        assert stat.S_IMODE(client.path.stat().st_mode) == 0o600


# [상황] 로그인하지 않고 "나는 누구?" 도구를 부른다.
# [기대] NOT_LOGGED_IN(먼저 로그인하세요) 오류를 낸다.
def test_로그인_전에는_안내_오류를_낸다(client: TraceClient) -> None:
    with pytest.raises(ApiError) as err:
        tools.whoami(client)
    assert err.value.code == "NOT_LOGGED_IN"


# [상황] 로그인 뒤 시간이 지나 접속 토큰이 만료됐다.
# [기대] 리프레시 토큰으로 한 번 새로 받아 요청을 이어 가고, 새 토큰을 세션 파일에 저장한다.
def test_액세스_토큰이_만료되면_리프레시로_한_번_재발급한다(client: TraceClient, gw: FakeGateway) -> None:
    client.login("me@example.com", "pw")
    gw.valid = "access-2"
    assert tools.get_rental(client, "R1")["rentalId"] == "R1"
    assert sess.load(client.path) == sess.Session("access-2", "refresh-2")


# [상황] 리프레시 토큰까지 무효다.
# [기대] LOGIN_EXPIRED(다시 로그인하세요) 오류를 낸다.
def test_리프레시도_실패하면_다시_로그인하라고_한다(client: TraceClient) -> None:
    sess.save(client.path, sess.Session("old", "bad"))
    with pytest.raises(ApiError) as err:
        tools.list_my_rentals(client)
    assert err.value.code == "LOGIN_EXPIRED"


# [상황] "진행 중(OPEN) 렌탈만" 목록을 부르고, 렌탈 번호 자리에 "../auth/me" 같은 꼼수를 넣는다.
# [기대] 상태 거르기는 주소에 붙고, 꼼수 글자는 인코딩되어 다른 API로 새지 않는다.
def test_상태로_렌탈을_거르고_경로_조각은_인코딩한다(client: TraceClient, gw: FakeGateway) -> None:
    client.login("me@example.com", "pw")
    assert tools.list_my_rentals(client, "OPEN")["path"] == "/rentals?status=OPEN"
    tools.get_rental(client, "../auth/me")
    assert gw.calls[-1][1] == "/rentals/..%2Fauth%2Fme"


# [상황] 렌탈 R1 요약을 부른다(출고 봉인, 수령 아직).
# [기대] 출고에는 검사 결과(등급 A)를 붙이고 진단은 "없음" 사유로 남긴다. 아직 촬영 전인 수령에는 붙이지 않는다.
def test_요약은_촬영이_끝난_시점만_결과를_붙이고_없는_결과는_사유로_남긴다(client: TraceClient) -> None:
    client.login("me@example.com", "pw")
    out = tools.summarize_rental(client, "R1")
    first, second = out["checkpoints"]
    assert first["name"] == "출고"
    assert first["inspection"] == {"result": {"grade": "A", "scratches": []}}
    assert first["diagnostics"] == {"result": None, "reason": "NOT_FOUND"}
    assert second["name"] == "수령" and "inspection" not in second


# [상황] 서버 주소를 암호화되지 않은 http로 준다(내 컴퓨터 localhost는 예외).
# [기대] 일반 http 주소는 거부하고, localhost는 개발용으로 허용한다.
def test_https가_아닌_주소는_거부한다(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        TraceClient("http://gakdo.example/", tmp_path / "s.json")
    TraceClient("http://localhost:8080/", tmp_path / "s.json")


# [상황] MCP 서버가 AI 앱에 알려 주는 도구 목록을 본다.
# [기대] 정확히 7개(나는 누구·내 렌탈 목록·렌탈 상세·검사 결과·진단 결과·기종 정보·렌탈 요약)이고,
#        모두 "읽기 전용" 표시가 있다. AI가 무언가를 바꾸는 도구는 없다.
def test_MCP_서버는_읽기_전용_도구_7개를_노출한다(client: TraceClient) -> None:
    server = pytest.importorskip("trace_mcp.server")
    app = server.build(client)
    listed = asyncio.run(app.list_tools())
    names = {t.name for t in listed}
    assert names == {"whoami", "list_my_rentals", "get_rental", "get_inspection",
                     "get_diagnostics", "get_device_model", "summarize_rental"}
    assert all(t.annotations and t.annotations.read_only_hint for t in listed)


# [상황] 토큰 재발급 중 서버가 잠깐 503(점검 중)으로 답한다.
# [기대] "로그인 만료"로 잘못 알리지 않고 그 오류(UNAVAILABLE)를 그대로 알린다.
#        ※ 응답 코드: 503 = 서버를 지금 쓸 수 없음(점검·장애)
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


# [상황] 로그아웃하는데 네트워크가 끊겨 서버에 알리지 못한다.
# [기대] 오류는 알리되, 내 컴퓨터의 세션 파일은 반드시 지운다.
def test_로그아웃은_서버_호출이_실패해도_로컬_세션을_지운다(client: TraceClient) -> None:
    sess.save(client.path, sess.Session("a", "r"))

    def down(method: str, url: str, headers: dict[str, str], data: bytes | None) -> Response:
        raise ApiError(503, "NETWORK_ERROR")

    client.http = down
    with pytest.raises(ApiError):
        client.logout()
    assert not client.path.exists()


# [상황] 서버 응답이 "다른 주소(evil.example)로 가라"는 302 리디렉션이다.
# [기대] 따라가지 않는다. 그래서 로그인 토큰이 엉뚱한 곳으로 보내지지 않는다.
#        ※ 응답 코드: 302 = 다른 주소로 가라는 안내(리디렉션)
def test_리디렉션은_따라가지_않아_토큰이_다른_주소로_가지_않는다() -> None:
    import email.message
    import io
    import urllib.request
    import urllib.response

    from trace_mcp import client as mod

    class Redirecting(urllib.request.BaseHandler):
        handler_order = 100  # 진짜 HTTPS 연결보다 먼저

        def https_open(self, req: urllib.request.Request) -> object:
            hdrs = email.message.Message()
            hdrs["Location"] = "http://evil.example/"
            resp = urllib.response.addinfourl(io.BytesIO(b""), hdrs, req.full_url, 302)
            resp.msg = "Found"
            return resp

    opener = urllib.request.build_opener(mod._NoRedirect, Redirecting)
    old = mod._OPENER
    mod._OPENER = opener
    try:
        resp = mod.http_request("GET", "https://gakdo.example/api/v1/auth/me", {"Authorization": "Bearer x"}, None)
    finally:
        mod._OPENER = old
    assert resp.status == 302
