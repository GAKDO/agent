"""보안 상태 점검(11/12, 사업단·기자재 담당자 설문 반영): Defender·Gatekeeper·SIP 켜짐 여부와 위협 건수만 읽는다."""

from __future__ import annotations

import json

from conftest import FixtureRunner
from test_windows import WinRunner, _doc

from trace_agent import macos, report, windows
from trace_agent.commands import ALLOWED, WINDOWS, Output

DEFENDER, THREATS = WINDOWS["DEFENDER"], WINDOWS["THREATS"]
ON = '{"AntivirusEnabled": true, "RealTimeProtectionEnabled": true}'


def _win(defender: str | None, threats: str | None) -> dict:
    overrides = {
        DEFENDER: Output(DEFENDER, 0, defender) if defender is not None else Output(DEFENDER, 1, "", "오류"),
        THREATS: Output(THREATS, 0, threats) if threats is not None else Output(THREATS, 1, "", "오류"),
    }
    return windows.collect(WinRunner(overrides))


def test_Defender가_모두_켜져_있고_위협이_없으면_ON과_0건을_올린다():
    collected = _win(ON, "0\n")
    doc = _doc(collected)
    assert doc["checks"]["securityProtection"] == "ON" and doc["checks"]["threatCount"] == 0
    assert report.errors(doc) == []
    assert "보안 보호: 켜짐, 위협 탐지 기록 0건" in report.summary(doc, collected["checks"])


def test_실시간_보호가_꺼져_있으면_OFF로_올리고_요약에_경고한다():
    collected = _win('{"AntivirusEnabled": true, "RealTimeProtectionEnabled": false}', "0")
    doc = _doc(collected)
    assert doc["checks"]["securityProtection"] == "OFF" and report.errors(doc) == []
    assert any("실시간 보호" in w for w in collected["checks"]["warnings"])


def test_위협_기록이_있으면_건수만_올리고_파일_경로는_올리지_않는다():
    collected = _win(ON, "3\r\n")
    doc = _doc(collected)
    assert doc["checks"]["threatCount"] == 3 and report.errors(doc) == []
    assert any("3건" in w for w in collected["checks"]["warnings"])
    assert "\\\\" not in json.dumps(doc["checks"])


def test_Defender를_읽지_못하면_보안_칸을_빼서_옛_서버도_받는다():
    doc = _doc(_win(None, None))
    assert "securityProtection" not in doc["checks"] and "threatCount" not in doc["checks"]
    assert report.errors(doc) == []


def test_맥은_Gatekeeper나_SIP가_꺼져_있으면_OFF이고_위협_건수는_올리지_않는다():
    off = macos.collect(FixtureRunner({macos.SIP: Output(macos.SIP, 0,
                                                         "System Integrity Protection status: disabled.\n")}))
    assert off["checks"]["security"] == "꺼짐" and any("SIP" in w for w in off["checks"]["warnings"])
    assert report.upload_checks(off["checks"])["securityProtection"] == "OFF"
    assert "threatCount" not in report.upload_checks(off["checks"])


def test_맥_SIP가_사용자_설정이라_확실하지_않으면_모름이다():
    custom = "System Integrity Protection status: unknown (Custom Configuration).\n"
    assert macos.security_protection("assessments enabled\n", custom) is None
    assert macos.security_protection("assessments disabled\n", custom) == "꺼짐"


def test_보안_명령도_고정_목록_안에_있고_위협_상세는_꺼내지_않는다():
    assert macos.GATEKEEPER in ALLOWED and macos.SIP in ALLOWED and DEFENDER in ALLOWED and THREATS in ALLOWED
    assert "Resources" not in " ".join(THREATS) and ".Count" in " ".join(THREATS)
