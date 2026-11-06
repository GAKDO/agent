"""스토리 3: 동의한 뒤에만 올린다."""

from __future__ import annotations

import json

from conftest import FixtureRunner

from trace_agent import macos, report
from trace_agent.__main__ import main
from trace_agent.commands import Output

ENV = {"TRACE_API_URL": "https://api.test"}
TOKEN = "agent-token-value"
AC = Output(macos.PMSET_BATT, 0, "Now drawing from 'AC Power'\n -InternalBattery-0 (id=1)\t100%; charged; present: true\n")


class FakeServer:
    def __init__(self, upload_status: int = 201, upload_body: dict | None = None) -> None:
        self.requests: list[tuple[str, dict, dict]] = []
        self.upload_status, self.upload_body = upload_status, upload_body or {"runId": "r1", "flags": []}

    def __call__(self, url: str, body: dict, headers: dict) -> tuple[int, dict]:
        self.requests.append((url, body, headers))
        if url.endswith("/pairing-codes/exchange"):
            return (200, {"accessToken": TOKEN}) if body["code"] == "482913" else (400, {"code": "PAIRING_CODE_INVALID"})
        return self.upload_status, self.upload_body


def clock():
    times = iter(["2026-11-02T11:00:00+09:00", "2026-11-02T11:01:30+09:00"])
    return lambda: next(times)


def fast_workloads() -> dict:
    return {m: ("ops/s", lambda: 1.0) for m in ("CPU_SINGLE", "CPU_MULTI", "MEM_COPY", "DISK_READ", "DISK_WRITE")}


def run_cli(server, answer: str, tmp_path, code: str | None = "482913", runner=None) -> int:
    argv = ["run", "--out", str(tmp_path / "diag.json")] + (["--code", code] if code else [])
    return main(argv, env=ENV, ask=lambda _q: answer, run=runner or FixtureRunner(), post=server,
                workloads=fast_workloads(), clock=clock(), system="darwin")  # 맥 고정 파일이라 CI windows에서도 macOS 수집기


def test_요약_뒤_y가_아니면_어떤_네트워크_요청도_보내지_않는다(tmp_path, capsys):
    server = FakeServer()
    assert run_cli(server, "n", tmp_path) == 0
    assert server.requests == []
    assert "올리지 않았어요" in capsys.readouterr().out


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


def test_서버가_409나_422를_주면_code를_보여_주고_1로_끝나며_JSON을_파일로_남긴다(tmp_path, capsys):
    server = FakeServer(409, {"code": "DIAGNOSTIC_ALREADY_UPLOADED", "detail": "이미 올림"})
    assert run_cli(server, "y", tmp_path) == 1
    assert "DIAGNOSTIC_ALREADY_UPLOADED" in capsys.readouterr().err
    saved = json.loads((tmp_path / "diag.json").read_text(encoding="utf-8"))
    assert saved["device"]["serial"] == "C02TEST00001"


def test_페어링_코드가_틀리면_무엇이_틀렸는지_알리고_업로드하지_않는다(tmp_path, capsys):
    server = FakeServer()
    assert run_cli(server, "y", tmp_path, code="000000") == 1
    assert "PAIRING_CODE_INVALID" in capsys.readouterr().err
    assert len(server.requests) == 1


def test_페어링_코드_없이_실행하면_결과만_보여_주고_파일로_남긴다(tmp_path, capsys):
    server = FakeServer()
    assert run_cli(server, "y", tmp_path, code=None) == 0
    assert server.requests == []
    assert (tmp_path / "diag.json").exists()
    assert "사이클 186" in capsys.readouterr().out


def test_전원이_없으면_명령줄에서도_벤치마크를_돌리지_않는다(tmp_path):
    called: list[int] = []
    workloads = {m: ("ops/s", lambda: called.append(1) or 1.0) for m in ("CPU_SINGLE",)}
    main(["run", "--out", str(tmp_path / "d.json")], env=ENV, ask=lambda _q: "n", run=FixtureRunner(),
         post=FakeServer(), workloads=workloads, clock=clock(), system="darwin")
    assert called == []
    assert json.loads((tmp_path / "d.json").read_text())["benchmarkSkippedReason"] == "NO_AC_POWER"


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


def test_교환이_429면_Retry_After만큼_기다렸다_다시_시도해_올린다(tmp_path):
    slept: list[float] = []
    server = RateLimitedServer()
    assert _cli(server, tmp_path, slept) == 0
    assert slept == [3.0]
    assert [u.rsplit("/", 1)[-1] for u, _, _ in server.requests] == ["exchange", "exchange", "runs"]


def test_페어링_코드의_기기와_시리얼이_다르면_올리지_않고_알린다(tmp_path, capsys):
    server = RateLimitedServer(device_serial="C02OTHER9999")
    assert _cli(server, tmp_path, []) == 1
    assert not any(u.endswith("/runs") for u, _, _ in server.requests)
    err = capsys.readouterr().err
    assert "끝 0001" in err and "끝 9999" in err and "C02TEST00001" not in err


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


def test_https가_아닌_주소면_경고하고_localhost는_경고하지_않는다(tmp_path, capsys):
    for api, warned in (("http://gakdo.example", True), ("http://localhost:8315", False)):
        main(["run", "--out", str(tmp_path / "d.json"), "--code", "482913"], env={"TRACE_API_URL": api},
             ask=lambda _q: "n", run=FixtureRunner(), post=FakeServer(), workloads=fast_workloads(), clock=clock(),
             system="darwin")
        assert ("https가 아니라" in capsys.readouterr().err) is warned
