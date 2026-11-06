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


def _known(value: Any, unit: str = "") -> str:
    return "모름" if value is None else f"{value}{unit}"


def spread_percent(trials: list[float], median: float) -> float:
    """3회 측정 편차 = (최댓값 - 최솟값) ÷ 2 ÷ 중앙값 × 100 (FR-DIA-04). 중앙값이 0이면 0."""
    return round((max(trials) - min(trials)) / 2 / median * 100, 1) if median else 0.0


def summary(doc: dict[str, Any], checks: dict[str, Any] | None = None) -> str:
    """동의 전에 보여 줄 요약. 올라갈 값과 실행한 명령을 그대로 보인다.
    checks(잠금 상태·경고)는 계약에 칸이 없어 올리지 않고 여기서만 보인다."""
    d, c, b, s = doc["device"], doc["conditions"], doc["battery"], doc["storage"]
    lines = [
        f"기기: {d['manufacturer']} {d.get('modelName') or d['model']} ({d['model']}), 시리얼 {d['serial']}",
        f"OS: {doc['os']['type']} {doc['os']['version']} {doc['os']['arch']}",
        "부품: " + ", ".join(f"{x['kind']} {x['identifier']}" for x in doc["components"]),
    ]
    # 올라가는 부품 식별값(시리얼·부품 번호)도 동의 전에 그대로 보인다
    ids = [f"{x['kind']} " + " ".join(f"{k} {x['detail'][k]}" for k in ("serial", "partNumber") if x["detail"].get(k))
           for x in doc["components"] if any(x["detail"].get(k) for k in ("serial", "partNumber"))]
    if ids:
        lines.append("부품 식별값: " + "; ".join(ids))
    if b["status"] == "OK":
        lines.append(
            f"배터리: 사이클 {b['cycleCount'] if b['cycleCount'] is not None else '모름'}, "
            f"설계 {_capacity(b['designCapacity'])}, 완충 {_capacity(b['fullChargeCapacity'])}, "
            f"OS 최대 용량 {'모름' if b['osMaxCapacityPercent'] is None else str(b['osMaxCapacityPercent']) + '%'}, "
            f"OS 판정 {b['osCondition'] or '모름'}"
        )
    else:
        lines.append(f"배터리: {b['status']}" + (f" (사유 {b['skippedReason']})" if b["skippedReason"] else ""))
    if s["status"] == "OK":
        lines.append(
            f"SSD: {s['protocol']}, 사용률 {_known(s['percentageUsed'], '%')}, 예비 {_known(s['availableSpare'], '%')}, "
            f"경고 {_known(s['criticalWarning'])}, 미디어 오류 {_known(s['mediaErrors'])}, "
            f"가동 {_known(s['powerOnHours'], '시간')}"
        )
    else:
        smart = next((x["detail"].get("smartStatus") for x in doc["components"]
                      if x["kind"] == "SSD" and x["detail"].get("smartStatus")), None)
        lines.append(f"SSD: 생략 (사유 {s['skippedReason']})" + (f", OS SMART 상태 {smart}" if smart else ""))
    pct = "모름" if c["batteryPercent"] is None else f"{c['batteryPercent']}%"
    lines.append(f"조건: 전원 {'연결' if c['acPower'] else '없음'}, 잔량 {pct}, 발열 {c['thermalState'] or '모름'}")
    if doc["benchmarks"]:
        lines.append("벤치마크(중앙값, 3회 편차): " + ", ".join(
            f"{x['metric']} {x['median']} {x['unit']} ±{spread_percent(x['trials'], x['median'])}%"
            for x in doc["benchmarks"]))
    else:
        lines.append(f"벤치마크: 돌리지 않음 (사유 {doc['benchmarkSkippedReason']})")
    if checks:
        locks = [f"{name} {checks[key] or '모름'}" for key, name in
                 (("activationLock", "활성화 잠금"), ("fileVault", "FileVault"), ("bitLocker", "BitLocker")) if key in checks]
        if locks:
            lines.append("잠금(올리지 않음): " + ", ".join(locks))
        lines += [f"[주의] {w}" for w in checks.get("warnings", [])]
    lines.append("실행한 명령: " + "; ".join(doc["sources"]))
    return "\n".join(lines)
