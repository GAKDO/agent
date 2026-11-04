"""Windows 명령 출력 → 진단 JSON 조각(AG2). 파서는 순수 함수이고 `collect`만 명령을 실행한다.

PowerShell(Get-CimInstance·Get-PhysicalDisk)은 고른 속성만 JSON으로 꺼낸다. 컴퓨터 이름(Name)·사용자 이름(UserName)·
UUID는 Select-Object에 넣지 않아 처음부터 읽지 않는다(헌법 V). 배터리 용량은 root/wmi의 mWh 원값을 그대로 쓴다.
SSD 수명 값은 smartctl이고, 관리자 권한이 없으면 SKIPPED + NO_PERMISSION으로 남는다.
"""

from __future__ import annotations

import json
import platform
import sys
from typing import Any

from .commands import WINDOWS, Output, Runner
from .macos import _SSD_NULLS, _int, _positive, parse_smartctl

SYSTEM, BIOS, CPU, MEMORY, DISKS, VIDEO = (WINDOWS[k] for k in ("SYSTEM", "BIOS", "CPU", "MEMORY", "DISKS", "VIDEO"))
BATTERY, BATTERY_STATIC, BATTERY_FULL, BATTERY_CYCLE, BATTERY_STATUS = (
    WINDOWS[k] for k in ("BATTERY", "BATTERY_STATIC", "BATTERY_FULL", "BATTERY_CYCLE", "BATTERY_STATUS"))
PROCESSES, UPTIME, SMARTCTL, SMARTCTL_DEFAULT_PATH = (
    WINDOWS[k] for k in ("PROCESSES", "UPTIME", "SMARTCTL", "SMARTCTL_DEFAULT_PATH"))

# Get-PhysicalDisk는 PowerShell 버전에 따라 숫자나 글자로 준다
_MEDIA = {3: "HDD", 4: "SSD", 5: "SCM"}
_BUS = {7: "USB", 11: "SATA", 17: "NVMe"}
_HEALTH = {0: "Healthy", 1: "Warning", 2: "Unhealthy", 5: "Unknown"}
_SKIP_NULLS = ("cycleCount", "designCapacity", "fullChargeCapacity", "osMaxCapacityPercent", "osCondition")
_PLACEHOLDER_SERIALS = {"", "to be filled by o.e.m.", "default string", "system serial number", "0", "none"}


def rows(text: str) -> list[dict[str, Any]]:
    """ConvertTo-Json은 하나면 객체, 여럿이면 배열, 없으면 빈 출력을 준다. 늘 목록으로."""
    try:
        data = json.loads(text) if text.strip() else []
    except json.JSONDecodeError:
        return []
    items = data if isinstance(data, list) else [data]
    return [i for i in items if isinstance(i, dict)]


def _str(value: Any, limit: int) -> str:
    return str(value).strip()[:limit] if value is not None else ""


def _label(value: Any, table: dict[int, str]) -> str | None:
    if isinstance(value, int) and not isinstance(value, bool):
        return table.get(value)
    return str(value) if value not in (None, "") else None


def parse_device(system: str, bios: str) -> dict[str, Any]:
    cs = (rows(system) or [{}])[0]
    serial = _str((rows(bios) or [{}])[0].get("SerialNumber"), 64)
    return {
        "serial": "" if serial.lower() in _PLACEHOLDER_SERIALS else serial,
        "manufacturer": _str(cs.get("Manufacturer"), 64),
        "model": _str(cs.get("Model"), 64),
        "modelName": _str(cs.get("SystemFamily"), 128) or None,
    }


def parse_cpu(text: str) -> list[dict[str, Any]]:
    out = []
    for p in rows(text):
        if not (name := _str(p.get("Name"), 128)):
            continue
        detail = {k: v for k, v in (("cores", _positive(p.get("NumberOfCores"))),
                                    ("logicalProcessors", _positive(p.get("NumberOfLogicalProcessors")))) if v}
        out.append({"kind": "CPU", "identifier": name, "detail": detail})
    return out


def parse_memory(text: str) -> list[dict[str, Any]]:
    total = sum(_int(m.get("Capacity")) or 0 for m in rows(text))
    if not total:
        return []
    return [{"kind": "RAM", "identifier": f"{round(total / 1024**3)} GB", "detail": {"totalBytes": total}}]


def parse_disks(text: str) -> list[dict[str, Any]]:
    out = []
    for d in rows(text):
        bus, media = _label(d.get("BusType"), _BUS), _label(d.get("MediaType"), _MEDIA)
        if bus == "USB" or not (name := _str(d.get("FriendlyName"), 128)):
            continue  # 꽂아 둔 USB 저장 장치는 기기 부품이 아니다
        detail = {k: v for k, v in (("serial", _str(d.get("SerialNumber"), 64) or None),
                                    ("capacityBytes", _positive(d.get("Size"))), ("busType", bus),
                                    ("mediaType", media), ("health", _label(d.get("HealthStatus"), _HEALTH)))
                  if v is not None}
        kind = "SSD" if media in ("SSD", "SCM") or bus == "NVMe" else "OTHER"
        out.append({"kind": kind, "identifier": name, "detail": detail})
    return out


def parse_video(text: str) -> list[dict[str, Any]]:
    out = []
    for v in rows(text):
        w, h = _positive(v.get("CurrentHorizontalResolution")), _positive(v.get("CurrentVerticalResolution"))
        if not (w and h):
            continue  # 화면을 내보내지 않는 어댑터(원격·가상)는 뺀다
        out.append({"kind": "DISPLAY", "identifier": _str(v.get("Name"), 128) or "Display",
                    "detail": {"resolution": f"{w}x{h}"}})
    return out


def _skipped_battery(reason: str) -> dict[str, Any]:
    return {"status": "SKIPPED", "skippedReason": reason, **dict.fromkeys(_SKIP_NULLS)}


def _denied(out: Output) -> bool:
    return "denied" in out.stderr.lower() or "액세스" in out.stderr


def parse_battery(battery: Output, static: Output, full: Output, cycle: Output
                  ) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """배터리 값과 BATTERY 부품. 용량은 root/wmi mWh 원값, 배터리가 둘이면 더한다. OS 판정·최대 용량 %는 Windows에 없어 null."""
    if not battery.ok:
        return _skipped_battery("TOOL_ERROR"), None
    if not rows(battery.stdout):
        return {"status": "NO_BATTERY", "skippedReason": None, **dict.fromkeys(_SKIP_NULLS)}, None
    statics = rows(static.stdout) if static.ok else []
    design = _positive(sum(_int(s.get("DesignedCapacity")) or 0 for s in statics))
    fulls = rows(full.stdout) if full.ok else []
    full_mwh = _positive(sum(_int(f.get("FullChargedCapacity")) or 0 for f in fulls))
    if design is None or full_mwh is None:
        return _skipped_battery("NO_PERMISSION" if _denied(static) or _denied(full) else "TOOL_ERROR"), None
    cycles = [_positive(c.get("CycleCount")) for c in (rows(cycle.stdout) if cycle.ok else [])]
    result = {
        "status": "OK",
        "skippedReason": None,
        "cycleCount": max((c for c in cycles if c), default=None),
        "designCapacity": {"value": design, "unit": "mWh"},
        "fullChargeCapacity": {"value": full_mwh, "unit": "mWh"},
        "osMaxCapacityPercent": None,
        "osCondition": None,
    }
    first = statics[0] if statics else {}
    name = _str(first.get("DeviceName"), 128) or _str(rows(battery.stdout)[0].get("Name"), 128) or "Battery"
    serial = _str(first.get("SerialNumber"), 64)
    return result, {"kind": "BATTERY", "identifier": name, "detail": {"serial": serial} if serial else {}}


def parse_conditions(battery: str, status: str, processes: str, uptime: str) -> dict[str, Any]:
    batteries = rows(battery)
    online = [s.get("PowerOnline") for s in rows(status) if isinstance(s.get("PowerOnline"), bool)]
    if not batteries:
        ac = True  # 배터리가 없으면 늘 전원에 꽂혀 있다
    elif online:
        ac = any(online)
    else:
        ac = any(b.get("BatteryStatus") in (2, 6, 7, 8, 9) for b in batteries)  # Win32_Battery: 2=AC, 6~9=충전 중
    pct = _int(batteries[0].get("EstimatedChargeRemaining")) if batteries else None
    count = _positive(processes.strip())
    up = _int(uptime.strip())
    return {
        "acPower": ac,
        "batteryPercent": pct if pct is not None and 0 <= pct <= 100 else None,
        "thermalState": None,  # 계약: Windows는 null
        "processCount": count,
        "uptimeSec": up if up is not None and up >= 0 else None,
    }


def parse_storage(out: Output) -> dict[str, Any]:
    lowered = out.stdout.lower()
    if out.code not in (None, 0) and ("denied" in lowered or "administrator" in lowered):
        return {"status": "SKIPPED", "skippedReason": "NO_PERMISSION", **dict.fromkeys(_SSD_NULLS)}
    return parse_smartctl(out)


def _os_version() -> str:
    """Windows는 platform.version()이 빌드 번호(10.0.22631)다. 다른 OS에서 테스트할 때는 release로 대신한다."""
    version = platform.version() if sys.platform == "win32" else platform.release()
    return (version or "unknown")[:32]


def collect(run: Runner) -> dict[str, Any]:
    """고정 목록 명령을 돌려 진단 JSON 조각(벤치마크·시각 제외)을 만든다."""
    outs = {argv: run(argv) for argv in (SYSTEM, BIOS, CPU, MEMORY, DISKS, VIDEO, BATTERY, BATTERY_STATIC,
                                         BATTERY_FULL, BATTERY_CYCLE, BATTERY_STATUS, PROCESSES, UPTIME, SMARTCTL)}
    smart = outs[SMARTCTL]
    if smart.code is None:  # PATH에 없으면 기본 설치 경로
        smart = outs[SMARTCTL_DEFAULT_PATH] = run(SMARTCTL_DEFAULT_PATH)

    def text(argv: tuple[str, ...]) -> str:
        return outs[argv].stdout if outs[argv].ok else ""

    components = parse_cpu(text(CPU)) + parse_memory(text(MEMORY)) + parse_disks(text(DISKS))
    battery, battery_part = parse_battery(outs[BATTERY], outs[BATTERY_STATIC], outs[BATTERY_FULL], outs[BATTERY_CYCLE])
    if battery_part:
        components.append(battery_part)
    components += parse_video(text(VIDEO))
    return {
        "os": {"type": "WINDOWS", "version": _os_version(), "arch": platform.machine()},
        "device": parse_device(text(SYSTEM), text(BIOS)),
        "conditions": parse_conditions(text(BATTERY), text(BATTERY_STATUS), text(PROCESSES), text(UPTIME)),
        "components": components,
        "battery": battery,
        "storage": parse_storage(smart),
        "sources": [o.source for o in outs.values()],
    }
