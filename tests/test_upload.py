"""이 파일이 확인하는 것: 진단 결과 올리기(요구사항 스토리 3: "고객이 동의한 뒤에만 올린다").
흐름: 진단 → 요약 보여 주기 → 고객이 y로 동의 → 6자리 페어링 코드를 토큰으로 교환 → 진단 서버로 올리기.
네트워크 대신 가짜 서버를 쓴다. 토큰 값 "agent-token-value"는 진짜가 아닌 임의 글자다.

스토리 3: 동의한 뒤에만 올린다.
"""

from __future__ import annotations

import json

import pytest
from conftest import FixtureRunner

from trace_agent import macos, report
from trace_agent.__main__ import main
from trace_agent.commands import Output

# 가짜 서버 주소.
ENV = {"TRACE_API_URL": "https://api.test"}
TOKEN = "agent-token-value"
# 충전기가 연결됐다고 답하는 전원 확인(pmset) 출력.
AC = Output(macos.PMSET_BATT, 0, "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t100%; charged; present: true\n")


# 가짜 TRACE 서버. 페어링 코드 482913만 맞는 코드로 받아 토큰을 주고, 진단 올리기에는 정한 상태 코드로 답한다.
class FakeServer:
    def __init__(self, upload_status: int = 201, upload_body: dict | None = None) -> None:
        self.requests: list[tuple[str, dict, dict]] = []
        self.upload_status, self.upload_body = upload_status, upload_body or {"runId": "r1", "flags": []}

    def __call__(self, url: str, body: dict, headers: dict) -> tuple[int, dict]:
        self.requests.append((url, body, headers))
        if url.endswith("/pairing-codes/exchange"):
            return (200, {"accessToken": TOKEN}) if body["code"] == "482913" else (400, {"code": "PAIRING_CODE_INVALID"})
        return self.upload_status, self.upload_body


# 가짜 시계: 첫 번째 값 = 수집 시각, 두 번째 값 = 고객이 y를 누른 시각.
def clock():
    times = iter(["2026-11-02T11:00:00+09:00", "2026-11-02T11:01:30+09:00"])
    return lambda: next(times)


def fast_workloads() -> dict:
    return {m: ("ops/s", lambda: 1.0) for m in ("CPU_SINGLE", "CPU_MULTI", "MEM_COPY", "DISK_READ", "DISK_WRITE")}


# 도우미: 고객 대답(answer)과 페어링 코드를 넣고 에이전트를 끝까지 실행한다.
def run_cli(server, answer: str, tmp_path, code: str | None = "482913", runner=None) -> int:
    argv = ["run", "--out", str(tmp_path / "diag.json")] + (["--code", code] if code else [])
    return main(argv, env=ENV, ask=lambda _q: answer, run=runner or FixtureRunner(), post=server,
                workloads=fast_workloads(), clock=clock(), system="darwin")  # 맥 고정 파일이라 CI windows에서도 macOS 수집기


# [상황] 요약을 본 고객이 n(아니오)을 넣는다.
# [기대] 서버로 아무 요청도 보내지 않고 "올리지 않았어요"라고 알린다.
def test_요약_뒤_y가_아니면_어떤_네트워크_요청도_보내지_않는다(tmp_path, capsys):
    server = FakeServer()
    assert run_cli(server, "n", tmp_path) == 0
    assert server.requests == []
    assert "올리지 않았어요" in capsys.readouterr().out


# [상황] 충전기가 연결된 상태에서 고객이 y를 넣는다.
# [기대] 먼저 페어링 코드를 토큰으로 바꾸고, 그 토큰과 중복 방지 키(Idempotency-Key)를 붙여 진단을 올린다.
#        수집 시각과 동의 시각(y를 누른 때)이 따로 적히고, 벤치마크 5개가 들어 있고, 스키마를 통과한다.
#        화면 어디에도 토큰 값이 나오지 않는다.
def test_y를_넣으면_페어링_교환_뒤_Idempotency_Key와_함께_올리고_consentedAt은_y를_넣은_시각이다(tmp_path, capsys):
    server = FakeServer()
    assert run_cli(server, "y", tmp_path, runner=FixtureRunner({macos.PMSET_BATT: AC})) == 0

    (url1, body1, _), (url2, doc, headers) = server.requests
    assert url1 == "https://api.test/api/v1/auth/pairing-codes/exchange" and body1 == {"code": "482913"}
    assert url2 == "https://api.test/api/v1/diagnostics/runs"
    assert headers["Authorization"] == f"Bearer {TOKEN}" and headers["Idempotency-Key"]
    assert doc["collectedAt"] == "2026-11-02T11:00:00+09:00"
    assert doc["consentedAt"] == "2026-11-02T11:01:30+09:00"
    assert len(doc["benchmarks"]) == 5 and doc["benchmarkSkippedReason"] is None
    assert report.errors(doc) == []
    out = capsys.readouterr()
    assert "올렸어요" in out.out and TOKEN not in out.out + out.err


# [상황] 서버가 "이미 올린 진단"(409)으로 거절한다.
# [기대] 오류 코드를 보여 주고 실패(1)로 끝나며, 진단 JSON은 파일로 남겨 둔다.
#        ※ 응답 코드: 409 = 지금 상태와 맞지 않아 거절(이미 있음·순서 어긋남 등)
def test_서버가_409나_422를_주면_code를_보여_주고_1로_끝나며_JSON을_파일로_남긴다(tmp_path, capsys):
    server = FakeServer(409, {"code": "DIAGNOSTIC_ALREADY_UPLOADED", "detail": "이미 올림"})
    assert run_cli(server, "y", tmp_path) == 1
    assert "DIAGNOSTIC_ALREADY_UPLOADED" in capsys.readouterr().err
    saved = json.loads((tmp_path / "diag.json").read_text(encoding="utf-8"))
    assert saved["device"]["serial"] == "C02TEST00001"


# [상황] 틀린 페어링 코드 000000을 넣는다.
# [기대] PAIRING_CODE_INVALID를 알리고, 진단은 올리지 않는다(교환 요청 1번뿐).
def test_페어링_코드가_틀리면_무엇이_틀렸는지_알리고_업로드하지_않는다(tmp_path, capsys):
    server = FakeServer()
    assert run_cli(server, "y", tmp_path, code="000000") == 1
    assert "PAIRING_CODE_INVALID" in capsys.readouterr().err
    assert len(server.requests) == 1


# [상황] 페어링 코드 없이 실행한다(렌탈 없이 내 노트북 상태만 보고 싶은 경우).
# [기대] 서버에 아무것도 보내지 않고 결과만 보여 주고 파일로 남긴다.
def test_페어링_코드_없이_실행하면_결과만_보여_주고_파일로_남긴다(tmp_path, capsys):
    server = FakeServer()
    assert run_cli(server, "y", tmp_path, code=None) == 0
    assert server.requests == []
    assert (tmp_path / "diag.json").exists()
    assert "사이클 186" in capsys.readouterr().out


# [상황] 충전기 없이 실행하고 충전기 질문에도 n을 넣는다.
# [기대] 벤치마크를 하나도 돌리지 않고 사유 NO_AC_POWER를 남긴다.
def test_전원이_없으면_명령줄에서도_벤치마크를_돌리지_않는다(tmp_path):
    called: list[int] = []
    workloads = {m: ("ops/s", lambda: called.append(1) or 1.0) for m in ("CPU_SINGLE",)}
    main(["run", "--out", str(tmp_path / "d.json")], env=ENV, ask=lambda _q: "n", run=FixtureRunner(),
         post=FakeServer(), workloads=workloads, clock=clock(), system="darwin")
    assert called == []
    assert json.loads((tmp_path / "d.json").read_text())["benchmarkSkippedReason"] == "NO_AC_POWER"


# 가짜 서버: 첫 페어링 교환은 "3초 뒤 다시"(429)로 막고, 다음부터 받아 준다. 교환 응답에 그 렌탈 기기 일련번호를 준다.
# ※ 응답 코드: 429 = 요청이 너무 잦아 잠시 막음
class RateLimitedServer(FakeServer):
    """처음 교환은 429(Retry-After 3)로 막고, 그다음부터 받아 준다. 교환 응답에 기기 시리얼을 준다."""

    def __init__(self, device_serial: str = "C02TEST00001", **kw) -> None:
        super().__init__(**kw)
        self.device_serial, self.limited = device_serial, True

    def __call__(self, url: str, body: dict, headers: dict) -> tuple[int, dict]:
        self.requests.append((url, body, headers))
        if url.endswith("/pairing-codes/exchange"):
            if self.limited:
                self.limited = False
                return 429, {"code": "RATE_LIMITED", "retryAfter": "3"}
            return 200, {"accessToken": TOKEN, "deviceSerial": self.device_serial}
        return self.upload_status, self.upload_body


def _cli(server, tmp_path, slept: list, argv: list[str] | None = None) -> int:
    argv = argv or ["run", "--out", str(tmp_path / "diag.json"), "--code", "482913"]
    return main(argv, env=ENV, ask=lambda _q: "y", run=FixtureRunner(), post=server, workloads=fast_workloads(),
                clock=clock(), system="darwin", sleep=slept.append)


# [상황] 페어링 교환이 요청 제한(429, 3초 뒤 다시)에 걸린다.
# [기대] 3초 기다렸다가 다시 교환하고 진단을 올린다.
#        ※ 응답 코드: 429 = 요청이 너무 잦아 잠시 막음
def test_교환이_429면_Retry_After만큼_기다렸다_다시_시도해_올린다(tmp_path):
    slept: list[float] = []
    server = RateLimitedServer()
    assert _cli(server, tmp_path, slept) == 0
    assert slept == [3.0]
    assert [u.rsplit("/", 1)[-1] for u, _, _ in server.requests] == ["exchange", "exchange", "runs"]


# [상황] 페어링 코드가 가리키는 렌탈 기기(끝 9999)와 지금 진단한 노트북(끝 0001)이 다르다.
# [기대] 다른 노트북의 진단이 섞이지 않게 올리지 않고, 두 기기의 끝 4자리만 보여 준다(전체 번호는 숨김).
def test_페어링_코드의_기기와_시리얼이_다르면_올리지_않고_알린다(tmp_path, capsys):
    server = RateLimitedServer(device_serial="C02OTHER9999")
    assert _cli(server, tmp_path, []) == 1
    assert not any(u.endswith("/runs") for u, _, _ in server.requests)
    err = capsys.readouterr().err
    assert "끝 0001" in err and "끝 9999" in err and "C02TEST00001" not in err


# [상황] 서버 점검(503)으로 올리기에 실패한 뒤, 나중에 "trace-agent upload"로 다시 올린다.
# [기대] 실패 때 진단 파일과 중복 방지 키를 남기고 다시 올리는 방법을 안내한다.
#        다시 올릴 때는 같은 키·같은 내용으로 보내 서버에 두 번 저장되지 않게 하고, 성공하면 키 파일을 지운다.
#        ※ 응답 코드: 503 = 서버를 지금 쓸 수 없음(점검·장애)
def test_올리지_못하면_JSON과_키를_남기고_upload_명령은_같은_키와_같은_내용으로_다시_올린다(tmp_path, capsys):
    first = FakeServer(503, {"code": "UNAVAILABLE"})
    assert run_cli(first, "y", tmp_path) == 1
    saved_key = (tmp_path / "diag.json.key").read_text()
    first_doc, first_key = first.requests[-1][1], first.requests[-1][2]["Idempotency-Key"]
    assert saved_key == first_key and "trace-agent upload" in capsys.readouterr().err

    again = FakeServer()
    argv = ["upload", "--file", str(tmp_path / "diag.json"), "--code", "482913"]
    assert main(argv, env=ENV, ask=lambda _q: "y", post=again, sleep=lambda _s: None) == 0
    _, doc, headers = again.requests[-1]
    assert headers["Idempotency-Key"] == first_key and doc == first_doc
    assert not (tmp_path / "diag.json.key").exists()


# [상황] 서버 주소를 암호화되지 않은 http로 준다(내 컴퓨터 localhost도 시험).
# [기대] 일반 http면 경고하고, localhost는 경고하지 않는다.
def test_https가_아닌_주소면_경고하고_localhost는_경고하지_않는다(tmp_path, capsys):
    for api, warned in (("http://gakdo.example", True), ("http://localhost:8315", False)):
        main(["run", "--out", str(tmp_path / "d.json"), "--code", "482913"], env={"TRACE_API_URL": api},
             ask=lambda _q: "n", run=FixtureRunner(), post=FakeServer(), workloads=fast_workloads(), clock=clock(),
             system="darwin")
        assert ("https가 아니라" in capsys.readouterr().err) is warned


# [상황] http 주소로 실행하고 y를 넣는다.
# [기대] 동의를 묻기 전(어떤 요청도 보내기 전)에 "보낼 곳: ... (암호화되지 않음"을 화면에 보여 준다.
def test_동의_질문_바로_위에_보낼_곳과_평문_여부를_보이고_교환보다_먼저_알린다(tmp_path, capsys):
    seen: list[str] = []

    def post(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        seen.append(capsys.readouterr().out)  # 첫 요청 전까지 화면에 나온 글
        return FakeServer()(url, body, headers)

    main(["run", "--out", str(tmp_path / "d.json"), "--code", "482913"], env={"TRACE_API_URL": "http://gakdo.example"},
         ask=lambda _q: "y", run=FixtureRunner(), post=post, workloads=fast_workloads(), clock=clock(), system="darwin")
    assert "보낼 곳: http://gakdo.example (암호화되지 않음" in seen[0]


# [상황] 중복 방지 키 파일이 비어 있는 채로 다시 올리기를 하고 또 실패한다.
# [기대] 새 키를 만들어 보내고, 실패했으니 그 키를 다시 남겨 둔다.
def test_빈_키_파일이면_새_키로_올리고_실패하면_그_키를_남긴다(tmp_path):
    run_cli(FakeServer(503, {"code": "UNAVAILABLE"}), "y", tmp_path)
    (tmp_path / "diag.json.key").write_text("")
    server = FakeServer(503, {"code": "UNAVAILABLE"})
    argv = ["upload", "--file", str(tmp_path / "diag.json"), "--code", "482913"]
    assert main(argv, env=ENV, ask=lambda _q: "y", post=server, sleep=lambda _s: None) == 1
    sent = server.requests[-1][2]["Idempotency-Key"]
    assert sent and (tmp_path / "diag.json.key").read_text() == sent


# [상황] https, localhost http, 일반 http 주소의 안내 문구를 만든다.
# [기대] 각각 "암호화(https)", "암호화되지 않음, 이 컴퓨터 안에서만", "토큰과 시리얼이 그대로(보임)".
def test_보낼_곳의_암호화_표시는_주소의_스킴으로_정한다():
    from trace_agent.__main__ import _target

    assert "암호화(https)" in _target("https://api.test")
    assert "암호화되지 않음, 이 컴퓨터 안에서만" in _target("http://localhost:8315")
    assert "토큰과 시리얼이 그대로" in _target("http://gakdo.example")


# [상황] 올리기 실패로 키가 남은 뒤, 코드 없이 새 진단을 다시 만든다.
# [기대] 지난 진단의 키는 지운다(새 진단에 옛 키를 쓰면 서버가 다른 진단으로 착각함).
def test_코드_없이_새로_남긴_진단에는_지난_진단의_키가_남지_않는다(tmp_path):
    run_cli(FakeServer(503, {"code": "UNAVAILABLE"}), "y", tmp_path)
    assert (tmp_path / "diag.json.key").exists()
    assert run_cli(FakeServer(), "y", tmp_path, code=None) == 0
    assert not (tmp_path / "diag.json.key").exists()


# [상황] 코드 없이 만든 진단 파일을 나중에 upload로 처음 올린다.
# [기대] 동의 시각은 그때 y를 누른 시각으로 적고, 수집 시각은 원래 값 그대로 둔다.
def test_키_없이_처음_올리는_JSON은_동의한_시각을_consentedAt에_적는다(tmp_path):
    assert run_cli(FakeServer(), "y", tmp_path, code=None) == 0
    server = FakeServer()
    argv = ["upload", "--file", str(tmp_path / "diag.json"), "--code", "482913"]
    assert main(argv, env=ENV, ask=lambda _q: "y", post=server, sleep=lambda _s: None,
                clock=lambda: "2026-11-02T12:00:00+09:00") == 0
    doc = server.requests[-1][1]
    assert doc["consentedAt"] == "2026-11-02T12:00:00+09:00" and doc["collectedAt"] == "2026-11-02T11:00:00+09:00"


# [상황] 위와 같이 처음 올리는 순간을 엿본다.
# [기대] 보내기 전에 보낼 본문과 키를 파일로 먼저 남긴다(중간에 끊겨도 같은 키·내용으로 다시 올릴 수 있게).
def test_키_없이_올리는_JSON은_보내기_전에_본문과_키를_함께_남긴다(tmp_path):
    assert run_cli(FakeServer(), "y", tmp_path, code=None) == 0
    seen: list[tuple[str, dict]] = []

    def post(url: str, body: dict, headers: dict) -> tuple[int, dict]:
        if url.endswith("/runs"):
            key = (tmp_path / "diag.json.key").read_text()
            saved = json.loads((tmp_path / "diag.json").read_text(encoding="utf-8"))
            assert key == headers["Idempotency-Key"] and saved == body  # 남긴 것과 보낸 것이 같아야 다시 올릴 수 있다
            seen.append((key, saved))
        return FakeServer()(url, body, headers)

    argv = ["upload", "--file", str(tmp_path / "diag.json"), "--code", "482913"]
    assert main(argv, env=ENV, ask=lambda _q: "y", post=post, sleep=lambda _s: None,
                clock=lambda: "2026-11-02T12:00:00+09:00") == 0
    key, saved = seen[0]
    assert key and saved["consentedAt"] == "2026-11-02T12:00:00+09:00"


# [상황] 서버 응답이 HTML·깨진 글자·빈 목록·null처럼 기대한 JSON이 아니다.
# [기대] 프로그램이 죽지 않고 "올리기 오류"로 바꿔 알린다.
def test_응답_본문이_JSON이_아니면_UploadError로_바꾼다(monkeypatch):
    import io

    from trace_agent import upload

    class Resp(io.BytesIO):
        status = 200

    for raw in (b"<html>", b"\xff", b"[]", b"null"):
        monkeypatch.setattr(upload._OPENER, "open", lambda *_a, _raw=raw, **_k: Resp(_raw))
        with pytest.raises(upload.UploadError):
            upload.http_post("https://api.test/x", {}, {})


# [상황] 오류 응답을 읽는 도중 연결이 끊긴다.
# [기대] "올리기 오류"로 바꿔 알린다.
def test_오류_본문을_읽다_끊기면_UploadError로_바꾼다(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    from trace_agent import upload

    class Broken(urllib.error.HTTPError):
        def read(self, *_a) -> bytes:  # type: ignore[override]
            raise ConnectionResetError("끊김")

    def raise_http(*_a, **_k):
        raise Broken("https://api.test/x", 503, "x", {}, io.BytesIO(b""))  # type: ignore[arg-type]

    monkeypatch.setattr(upload._OPENER, "open", raise_http)
    with pytest.raises(upload.UploadError):
        upload.http_post("https://api.test/x", {}, {})


# [상황] 새 진단을 저장하다 디스크 공간 부족으로 실패한다.
# [기대] 예전 진단 파일은 그대로 남고, 쓰다 만 임시 파일도 남지 않는다.
def test_저장이_실패해도_기존_진단_JSON은_그대로_남는다(tmp_path, monkeypatch):
    from trace_agent import __main__ as cli

    out = tmp_path / "diag.json"
    out.write_text('{"old": true}', encoding="utf-8")
    monkeypatch.setattr(cli.os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("공간 부족")))
    with pytest.raises(OSError):
        cli._save({"new": True}, out, "k")
    assert out.read_text(encoding="utf-8") == '{"old": true}'
    assert not (tmp_path / "diag.json.tmp").exists()


# [상황] 503 오류 응답 본문이 깨진 글자다.
# [기대] 본문은 빈 것으로 보고 상태 코드 503만 돌려준다.
#        ※ 응답 코드: 503 = 서버를 지금 쓸 수 없음(점검·장애)
def test_잘못_인코딩된_오류_응답은_빈_본문으로_읽는다(monkeypatch):
    import io
    import urllib.error
    import urllib.request

    from trace_agent import upload

    def raise_http(*_a, **_k):
        raise urllib.error.HTTPError("https://api.test/x", 503, "x", {}, io.BytesIO(b"\xff"))  # type: ignore[arg-type]

    monkeypatch.setattr(upload._OPENER, "open", raise_http)
    assert upload.http_post("https://api.test/x", {}, {}) == (503, {})


# [상황] 응답이 약속한 길이보다 일찍 끊긴다.
# [기대] "올리기 오류"로 바꿔 알린다.
def test_응답이_Content_Length보다_일찍_끝나면_UploadError로_바꾼다(monkeypatch):
    import http.client

    from trace_agent import upload

    class Short:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_a) -> None:
            return None

        def read(self) -> bytes:
            raise http.client.IncompleteRead(b"{", 10)

    monkeypatch.setattr(upload._OPENER, "open", lambda *_a, **_k: Short())
    with pytest.raises(upload.UploadError):
        upload.http_post("https://api.test/x", {}, {})


# [상황] 서버가 다른 주소(evil.test)로 가라고 302 리디렉션한다.
# [기대] 따라가지 않아 토큰이 다른 곳으로 가지 않는다.
#        ※ 응답 코드: 302 = 다른 주소로 가라는 안내(리디렉션)
def test_리다이렉트는_따라가지_않아_토큰이_다른_곳으로_가지_않는다():
    import urllib.request

    from trace_agent import upload

    req = urllib.request.Request("https://api.test/x", headers={"Authorization": "Bearer t"})
    handler = upload._NoRedirect()
    assert handler.redirect_request(req, None, 302, "Found", {}, "http://evil.test/") is None
