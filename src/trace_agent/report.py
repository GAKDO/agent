"""진단 JSON 조립 결과를 contracts 스키마(diag.v1)로 검증하고 사람이 읽을 요약을 만든다."""

from __future__ import annotations

import json
from functools import cache
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_VERSION = "diag.v1"
_BASE = "https://raw.githubusercontent.com/GAKDO/contracts/main/"


@cache
def validator() -> Draft202012Validator:
    root = files("trace_agent") / "schema"
    result = json.loads((root / "diagnostics" / "result.schema.json").read_text(encoding="utf-8"))
    codes = json.loads((root / "schemas" / "codes.gen.schema.json").read_text(encoding="utf-8"))
    result.setdefault("$id", _BASE + "diagnostics/result.schema.json")
    registry = Registry().with_resources(
        [(result["$id"], Resource.from_contents(result)), (codes["$id"], Resource.from_contents(codes))]
    )
    return Draft202012Validator(result, registry=registry)


def assemble(collected: dict[str, Any], *, agent_version: str, collected_at: str, consented_at: str,
             benchmarks: list[dict[str, Any]], benchmark_skipped_reason: str | None) -> dict[str, Any]:
    """수집 결과·벤치마크·시각을 스키마 순서대로 묶는다."""
    return {
        "schemaVersion": SCHEMA_VERSION,
        "agentVersion": agent_version,
        "collectedAt": collected_at,
        "consentedAt": consented_at,
        "os": collected["os"],
        "device": collected["device"],
        "conditions": collected["conditions"],
        "components": collected["components"],
        "battery": collected["battery"],
        "storage": collected["storage"],
        "benchmarks": benchmarks,
        "benchmarkSkippedReason": benchmark_skipped_reason,
        "sources": collected["sources"],
    }


def errors(doc: dict[str, Any]) -> list[str]:
    """스키마를 통과하지 못한 곳을 '경로: 이유'로. 통과하면 빈 목록."""
    found = sorted(validator().iter_errors(doc), key=lambda e: list(e.absolute_path))
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '(최상위)'}: {e.message}" for e in found]


def _capacity(value: dict[str, Any] | None) -> str:
    return f"{value['value']} {value['unit']}" if value else "모름"


def summary(doc: dict[str, Any]) -> str:
    """동의 전에 보여 줄 요약. 올라갈 값과 실행한 명령을 그대로 보인다."""
    d, c, b, s = doc["device"], doc["conditions"], doc["battery"], doc["storage"]
    lines = [
        f"기기: {d['manufacturer']} {d.get('modelName') or d['model']} ({d['model']}), 시리얼 {d['serial']}",
        f"OS: {doc['os']['type']} {doc['os']['version']} {doc['os']['arch']}",
        "부품: " + ", ".join(f"{x['kind']} {x['identifier']}" for x in doc["components"]),
    ]
    if b["status"] == "OK":
        lines.append(
            f"배터리: 사이클 {b['cycleCount'] if b['cycleCount'] is not None else '모름'}, "
            f"설계 {_capacity(b['designCapacity'])}, 완충 {_capacity(b['fullChargeCapacity'])}, "
            f"OS 최대 용량 {b['osMaxCapacityPercent'] if b['osMaxCapacityPercent'] is not None else '모름'}%, "
            f"OS 판정 {b['osCondition'] or '모름'}"
        )
    else:
        lines.append(f"배터리: {b['status']}" + (f" (사유 {b['skippedReason']})" if b["skippedReason"] else ""))
    if s["status"] == "OK":
        lines.append(
            f"SSD: {s['protocol']}, 사용률 {s['percentageUsed']}%, 예비 {s['availableSpare']}%, "
            f"경고 {s['criticalWarning']}, 미디어 오류 {s['mediaErrors']}, 가동 {s['powerOnHours']}시간"
        )
    else:
        lines.append(f"SSD: 생략 (사유 {s['skippedReason']})")
    lines.append(f"조건: 전원 {'연결' if c['acPower'] else '없음'}, 잔량 {c['batteryPercent']}%, 발열 {c['thermalState']}")
    if doc["benchmarks"]:
        lines.append("벤치마크: " + ", ".join(f"{x['metric']} {x['median']} {x['unit']}" for x in doc["benchmarks"]))
    else:
        lines.append(f"벤치마크: 돌리지 않음 (사유 {doc['benchmarkSkippedReason']})")
    lines.append("실행한 명령: " + "; ".join(doc["sources"]))
    return "\n".join(lines)
