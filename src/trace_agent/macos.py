"""macOS 명령 출력 → 진단 JSON 조각. 파서는 순수 함수이고 `collect`만 명령을 실행한다.

읽지 못한 값은 null, 못 읽은 항목은 SKIPPED + 사유(헌법 III). 컴퓨터 이름·UUID는 꺼내지 않는다.
"""

from __future__ import annotations

import json
import platform
import plistlib
import re
import time
from datetime import datetime
from typing import Any

from .commands import Output, Runner

HARDWARE = ("system_profiler", "SPHardwareDataType", "-json")
POWER = ("system_profiler", "SPPowerDataType", "-json")
NVME = ("system_profiler", "SPNVMeDataType", "-json")
DISPLAYS = ("system_profiler", "SPDisplaysDataType", "-json")
IOREG_BATTERY = ("ioreg", "-r", "-a", "-c", "AppleSmartBattery")
PMSET_BATT = ("pmset", "-g", "batt")
PMSET_THERM = ("pmset", "-g", "therm")
SMARTCTL = ("smartctl", "-j", "-a", "disk0")
PS = ("ps", "-A", "-o", "pid=")
BOOTTIME = ("sysctl", "-n", "kern.boottime")

_SKIP_NULLS = ("cycleCount", "designCapacity", "fullChargeCapacity", "osMaxCapacityPercent", "osCondition")
_SSD_NULLS = ("protocol", "percentageUsed", "availableSpare", "criticalWarning", "mediaErrors", "powerOnHours")


def _sp_items(text: str, key: str) -> list[dict[str, Any]]:
    try:
        return list(json.loads(text).get(key, []))
    except (json.JSONDecodeError, AttributeError):
        return []


def _int(value: Any) -> int | None:
    """'90%'·'16 GB'·186 같은 값에서 정수. 못 읽으면 None."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    m = re.search(r"\d+", str(value))
    return int(m[0]) if m else None


def _positive(value: Any) -> int | None:
    """0은 '모름'으로 쓰지 않는다."""
    n = _int(value)
    return n if n and n > 0 else None


def parse_hardware(text: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    hw = (_sp_items(text, "SPHardwareDataType") or [{}])[0]
    device = {
        "serial": hw.get("serial_number") or "",
        "manufacturer": "Apple",
        "model": hw.get("machine_model") or "",
        "modelName": hw.get("machine_name") or None,
    }
    components: list[dict[str, Any]] = []
    if hw.get("chip_type") or hw.get("cpu_type"):
        procs = [int(x) for x in re.findall(r"\d+", str(hw.get("number_processors", "")))]
        detail: dict[str, Any] = {"cores": procs[0]} if procs else {}
        if len(procs) >= 3:
            detail |= {"performanceCores": procs[1], "efficiencyCores": procs[2]}
        components.append({"kind": "CPU", "identifier": hw.get("chip_type") or hw["cpu_type"], "detail": detail})
    if gb := _int(hw.get("physical_memory")):
        components.append({"kind": "RAM", "identifier": f"{gb} GB", "detail": {"totalBytes": gb * 1024**3}})
    return device, components


def parse_nvme(text: str) -> list[dict[str, Any]]:
    disks = [d for ctrl in _sp_items(text, "SPNVMeDataType") for d in ctrl.get("_items", [])]
    return [
        {
            "kind": "SSD",
            "identifier": d.get("device_model") or d.get("_name"),
            "detail": {k: v for k, v in (("serial", d.get("device_serial")), ("capacityBytes", d.get("size_in_bytes")),
                                          ("smartStatus", d.get("smart_status"))) if v is not None},
        }
        for d in disks if d.get("device_model") or d.get("_name")
    ]


def parse_displays(text: str) -> list[dict[str, Any]]:
    screens = [s for gpu in _sp_items(text, "SPDisplaysDataType") for s in gpu.get("spdisplays_ndrvs", [])]
    out = []
    for s in screens:
        pixels = re.sub(r"\s*x\s*", "x", s.get("_spdisplays_pixels", "")).strip()
        out.append({"kind": "DISPLAY", "identifier": s.get("_name") or "Display",
                    "detail": {"resolution": pixels} if pixels else {}})
    return out


def parse_ioreg_battery(data: bytes) -> dict[str, Any] | None:
    try:
        items = plistlib.loads(data)
    except Exception:  # noqa: BLE001 — 형식이 다르면 '못 읽음'
        return None
    return items[0] if isinstance(items, list) and items else None


def parse_battery(power_text: str, ioreg: dict[str, Any] | None) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """배터리 값과 BATTERY 부품. 사이클·최대 용량 %·판정은 OS(system_profiler), mAh는 ioreg 원값."""
    info = next((i for i in _sp_items(power_text, "SPPowerDataType") if i.get("_name") == "spbattery_information"), None)
    no_battery = {"status": "NO_BATTERY", "skippedReason": None, **dict.fromkeys(_SKIP_NULLS)}
    if ioreg is not None and not ioreg.get("BatteryInstalled", True):
        return no_battery, None
    if ioreg is None and info is None:
        # 전원 정보는 읽었는데 배터리 항목이 없으면 배터리 없는 맥, 둘 다 못 읽었으면 도구 오류
        return (no_battery if power_text else {"status": "SKIPPED", "skippedReason": "TOOL_ERROR",
                                               **dict.fromkeys(_SKIP_NULLS)}), None
    health = (info or {}).get("sppower_battery_health_info", {})
    design = _positive(ioreg.get("DesignCapacity")) if ioreg else None
    full = (_positive(ioreg.get("NominalChargeCapacity")) or _positive(ioreg.get("AppleRawMaxCapacity"))) if ioreg else None
    if design is None or full is None:
        return {"status": "SKIPPED", "skippedReason": "TOOL_ERROR", **dict.fromkeys(_SKIP_NULLS)}, None
    condition = health.get("sppower_battery_health")
    battery = {
        "status": "OK",
        "skippedReason": None,
        "cycleCount": _positive(health.get("sppower_battery_cycle_count")),
        "designCapacity": {"value": design, "unit": "mAh"},
        "fullChargeCapacity": {"value": full, "unit": "mAh"},
        "osMaxCapacityPercent": _int(health.get("sppower_battery_health_maximum_capacity")),
        "osCondition": None if not condition else ("NORMAL" if condition in ("Good", "Normal") else "SERVICE_RECOMMENDED"),
    }
    model = (info or {}).get("sppower_battery_model_info", {})
    name = ioreg.get("DeviceName") or model.get("sppower_battery_device_name") or "Battery"
    serial = ioreg.get("Serial") or model.get("sppower_battery_serial_number")
    component = {"kind": "BATTERY", "identifier": name, "detail": {"serial": serial} if serial else {}}
    return battery, component


def parse_smartctl(out: Output) -> dict[str, Any]:
    def skipped(reason: str) -> dict[str, Any]:
        return {"status": "SKIPPED", "skippedReason": reason, **dict.fromkeys(_SSD_NULLS)}

    if out.code is None:
        return skipped("TOOL_ERROR")
    try:
        data = json.loads(out.stdout)
    except json.JSONDecodeError:
        return skipped("TOOL_ERROR")
    messages = " ".join(m.get("string", "") for m in data.get("smartctl", {}).get("messages", [])).lower()
    if "permission" in messages or "operation not permitted" in messages:
        return skipped("NO_PERMISSION")
    log = data.get("nvme_smart_health_information_log")
    if log:
        return {"status": "OK", "skippedReason": None, "protocol": "NVME",
                "percentageUsed": log.get("percentage_used"), "availableSpare": log.get("available_spare"),
                "criticalWarning": log.get("critical_warning"), "mediaErrors": log.get("media_errors"),
                "powerOnHours": log.get("power_on_hours")}
    if data.get("ata_smart_attributes"):
        return {"status": "OK", "skippedReason": None, "protocol": "ATA", "percentageUsed": None,
                "availableSpare": None, "criticalWarning": None, "mediaErrors": None,
                "powerOnHours": (data.get("power_on_time") or {}).get("hours")}
    return skipped("UNSUPPORTED" if out.code == 0 else "TOOL_ERROR")


def parse_conditions(batt: str, therm: str, ps: str, boottime: str, now: float) -> dict[str, Any]:
    ac = "AC Power" in batt.splitlines()[0] if batt.strip() else False
    pct = re.search(r"(\d+)%", batt)
    if not therm.strip():
        thermal = None
    elif "No thermal warning level has been recorded" in therm:
        thermal = "NOMINAL"
    else:
        thermal = "FAIR"
    count = len([line for line in ps.splitlines() if line.strip()]) or None
    boot = re.search(r"sec\s*=\s*(\d+)", boottime)
    return {
        "acPower": ac,
        "batteryPercent": int(pct[1]) if pct else None,
        "thermalState": thermal,
        "processCount": count,
        "uptimeSec": max(0, int(now) - int(boot[1])) if boot else None,
    }


def collect(run: Runner, now: float | None = None) -> dict[str, Any]:
    """고정 목록 명령을 돌려 진단 JSON 조각(벤치마크·시각 제외)을 만든다."""
    outs = {argv: run(argv) for argv in (HARDWARE, POWER, NVME, DISPLAYS, IOREG_BATTERY, PMSET_BATT,
                                         PMSET_THERM, SMARTCTL, PS, BOOTTIME)}

    def text(argv: tuple[str, ...]) -> str:
        return outs[argv].stdout if outs[argv].ok else ""

    device, components = parse_hardware(text(HARDWARE))
    components += parse_nvme(text(NVME))
    battery, battery_part = parse_battery(text(POWER), parse_ioreg_battery(text(IOREG_BATTERY).encode()))
    if battery_part:
        components.append(battery_part)
    components += parse_displays(text(DISPLAYS))
    return {
        "os": {"type": "MACOS", "version": platform.mac_ver()[0] or platform.release(), "arch": platform.machine()},
        "device": device,
        "conditions": parse_conditions(text(PMSET_BATT), text(PMSET_THERM), text(PS), text(BOOTTIME),
                                       time.time() if now is None else now),
        "components": components,
        "battery": battery,
        "storage": parse_smartctl(outs[SMARTCTL]),
        "sources": [o.source for o in outs.values()],
    }


def iso_now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
