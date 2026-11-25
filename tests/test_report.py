"""이 파일이 확인하는 것: 수집한 값으로 진단 JSON(서버에 올릴 문서)을 만들고, 계약의 진단 JSON 스키마로 검사하고,
고객에게 보여 줄 요약 글을 만드는 부분. 실제 맥 출력 고정 파일을 쓴다.

진단 JSON 조립·스키마 검증·요약.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import NOW

from trace_agent import macos, report

CONTRACTS = Path(__file__).parent / "fixtures" / "contracts"


# 도우미: 맥 고정 출력으로 진단 문서를 만든다(충전기가 없어 벤치마크는 건너뛴 상태).
def document(runner) -> dict:
    collected = macos.collect(runner, now=NOW)
    return report.assemble(collected, agent_version="0.1.0", collected_at="2026-11-02T10:58:00+09:00",
                           consented_at="2026-11-02T10:59:00+09:00", benchmarks=[],
                           benchmark_skipped_reason="NO_AC_POWER")


# [상황] 실제 맥북 출력으로 진단 JSON을 만든다.
# [기대] 계약(contracts)의 진단 JSON 스키마 검사에 오류가 하나도 없다(서버가 받아 줄 모양).
def test_맥_명령_출력으로_만든_진단은_contracts_진단_JSON_Schema를_통과한다(runner):
    assert report.errors(document(runner)) == []


# [상황] 에이전트 안에 들어 있는 스키마 복사본으로 계약의 "통과 예시"와 "실패 예시"(컴퓨터 이름 포함)를 검사한다.
# [기대] 통과 예시는 통과, 실패 예시는 실패. 즉 복사본이 계약 원본과 같은 판단을 한다.
def test_스키마_복사본은_contracts_예시의_통과와_실패를_그대로_가른다():
    assert report.errors(json.loads((CONTRACTS / "valid-macos.json").read_text())) == []
    assert report.errors(json.loads((CONTRACTS / "invalid-computer-name.json").read_text())) != []


# [상황] 명령 출력에는 기기 고유 UUID·모니터 일련번호 같은 값이 들어 있다.
# [기대] 그런 값은 진단 JSON 어디에도 들어가지 않는다(필요 없는 개인 식별 정보는 올리지 않음).
def test_명령_출력의_플랫폼_UUID나_디스플레이_시리얼은_JSON_어디에도_없다(runner):
    text = json.dumps(document(runner))
    for value in ("00000000-0000-0000-0000-000000000000", "DISPTEST01", "platform_UUID", "provisioning"):
        assert value not in text


# [상황] 배터리 충전 횟수를 허용되지 않는 값(0)으로 바꿔 검사한다.
# [기대] 오류 목록에 "battery/cycleCount"처럼 어느 칸이 틀렸는지 나온다.
def test_스키마를_통과하지_못하면_어느_필드인지_알린다(runner):
    doc = document(runner)
    doc["battery"]["cycleCount"] = 0
    assert any(e.startswith("battery/cycleCount") for e in report.errors(doc))


# [상황] 고객에게 "이 내용을 올려도 될까요?" 전에 보여 줄 요약을 만든다.
# [기대] 배터리 충전 186회·설계 용량 4563mAh·OS 최대 용량 90%, SSD 생략 사유, 벤치마크 안 한 사유,
#        그리고 실제로 실행한 명령까지 보인다(무엇을 읽었는지 투명하게).
def test_요약에는_올라갈_값과_실행한_명령이_보인다(runner):
    text = report.summary(document(runner))
    assert "사이클 186" in text and "4563 mAh" in text and "OS 최대 용량 90%" in text
    assert "SSD: 생략 (사유 TOOL_ERROR)" in text
    assert "벤치마크: 돌리지 않음 (사유 NO_AC_POWER)" in text
    assert "system_profiler SPHardwareDataType -json" in text


# [상황] 벤치마크 3번 측정값이 90·100·110이다.
# [기대] 편차 = (최대-최소)/2 ÷ 가운데 값 = 10%. 모두 0이면 0%.
def test_3회_측정_편차는_범위의_절반을_중앙값으로_나눈_백분율이다():
    assert report.spread_percent([90.0, 100.0, 110.0], 100.0) == 10.0
    assert report.spread_percent([0.0, 0.0, 0.0], 0.0) == 0.0
