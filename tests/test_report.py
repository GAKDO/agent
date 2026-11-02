"""진단 JSON 조립·스키마 검증·요약."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import NOW

from trace_agent import macos, report

CONTRACTS = Path(__file__).parent / "fixtures" / "contracts"


def document(runner) -> dict:
    collected = macos.collect(runner, now=NOW)
    return report.assemble(collected, agent_version="0.1.0", collected_at="2026-11-02T10:58:00+09:00",
                           consented_at="2026-11-02T10:59:00+09:00", benchmarks=[],
                           benchmark_skipped_reason="NO_AC_POWER")


def test_맥_명령_출력으로_만든_진단은_contracts_진단_JSON_Schema를_통과한다(runner):
    assert report.errors(document(runner)) == []


def test_스키마_복사본은_contracts_예시의_통과와_실패를_그대로_가른다():
    assert report.errors(json.loads((CONTRACTS / "valid-macos.json").read_text())) == []
    assert report.errors(json.loads((CONTRACTS / "invalid-computer-name.json").read_text())) != []


def test_명령_출력의_플랫폼_UUID나_디스플레이_시리얼은_JSON_어디에도_없다(runner):
    text = json.dumps(document(runner))
    for value in ("00000000-0000-0000-0000-000000000000", "DISPTEST01", "platform_UUID", "provisioning"):
        assert value not in text


def test_스키마를_통과하지_못하면_어느_필드인지_알린다(runner):
    doc = document(runner)
    doc["battery"]["cycleCount"] = 0
    assert any(e.startswith("battery/cycleCount") for e in report.errors(doc))


def test_요약에는_올라갈_값과_실행한_명령이_보인다(runner):
    text = report.summary(document(runner))
    assert "사이클 186" in text and "4563 mAh" in text and "OS 최대 용량 90%" in text
    assert "SSD: 생략 (사유 TOOL_ERROR)" in text
    assert "벤치마크: 돌리지 않음 (사유 NO_AC_POWER)" in text
    assert "system_profiler SPHardwareDataType -json" in text
