"""Windows 명령 출력 → 진단 JSON 조각(AG2). 파서는 순수 함수이고 `collect`만 명령을 실행한다.

PowerShell(Get-CimInstance·Get-PhysicalDisk)은 고른 속성만 JSON으로 꺼낸다. 컴퓨터 이름(Name)·사용자 이름(UserName)·
UUID는 Select-Object에 넣지 않아 처음부터 읽지 않는다(헌법 V). 배터리 용량은 root/wmi의 mWh 원값을 그대로 쓴다.
SSD 수명 값은 smartctl이고, 관리자 권한이 없으면 SKIPPED + NO_PERMISSION으로 남는다.
"""

from __future__ import annotations

import json
import os
import platform
import sys
import tempfile
from typing import Any

from .commands import WINDOWS, Output, Runner
from .macos import _SSD_NULLS, _int, _positive, parse_smartctl

SYSTEM, BIOS, CPU, MEMORY, DISKS, VIDEO = (WINDOWS[k] for k in ("SYSTEM", "BIOS", "CPU", "MEMORY", "DISKS", "VIDEO"))
BATTERY, BATTERY_STATIC, BATTERY_FULL, BATTERY_CYCLE, BATTERY_STATUS = (
    WINDOWS[k] for k in ("BATTERY", "BATTERY_STATIC", "BATTERY_FULL", "BATTERY_CYCLE", "BATTERY_STATUS"))
PROCESSES, UPTIME, SMARTCTL, SMARTCTL_DEFAULT_PATH = (
    WINDOWS[k] for k in ("PROCESSES", "UPTIME", "SMARTCTL", "SMARTCTL_DEFAULT_PATH"))
BATTERY_REPORT, BATTERY_REPORT_READ = WINDOWS["BATTERY_REPORT"], WINDOWS["BATTERY_REPORT_READ"]
RELIABILITY, BITLOCKER = WINDOWS["RELIABILITY"], WINDOWS["BITLOCKER"]
REPORT_FILE = "trace-battery.xml"  # %TEMP% 안. 읽은 뒤 지운다

# Get-PhysicalDisk는 PowerShell 버전에 따라 숫자나 글자로 준다
_MEDIA = {3: "HDD", 4: "SSD", 5: "SCM"}
_BUS = {7: "USB", 11: "SATA", 17: "NVMe"}
_HEALTH = {0: "Healthy", 1: "Warning", 2: "Unhealthy", 5: "Unknown"}
_SKIP_NULLS = ("cycleCount", "designCapacity", "fullChargeCapacity", "osMaxCapacityPercent", "osCondition")
_PLACEHOLDER_SERIALS = {"", "to be filled by o.e.m.", "default string", "system serial number", "0", "none"}


def _real_serial(value: str) -> bool:
    """제조사가 채우지 않은 자리표시 시리얼(00000000 등)은 부품 비교에 쓰지 않는다."""
    return value.lower() not in _PLACEHOLDER_SERIALS and set(value) != {"0"}


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
    """RAM은 하나의 부품으로 묶되, 모듈 시리얼을 detail.serial에 모아 같은 용량 모듈로 바꿔 끼운 것도 서버가 잡게 한다."""
    modules = rows(text)
    total = sum(_int(m.get("Capacity")) or 0 for m in modules)
    if not total:
        return []
    detail: dict[str, Any] = {"totalBytes": total, "modules": len(modules)}
    serials = sorted(s for m in modules if _real_serial(s := _str(m.get("SerialNumber"), 32)))
    if serials:
        detail["serial"] = ",".join(serials)[:128]
    parts = sorted({p for m in modules if (p := _str(m.get("PartNumber"), 32))})
    if parts:
        detail["partNumber"] = ",".join(parts)[:128]
    return [{"kind": "RAM", "identifier": f"{round(total / 1024**3)} GB", "detail": detail}]


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


def _sum(items: list[dict[str, Any]], key: str) -> int | None:
    return _positive(sum(_int(i.get(key)) or 0 for i in items))


def parse_battery(battery: Output, static: Output, full: Output, cycle: Output, report: Output | None = None
                  ) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """배터리 값과 BATTERY 부품. 용량은 root/wmi mWh 원값, 못 읽은 값은 배터리 리포트(powercfg) mWh로 채운다.
    배터리가 둘이면 더한다. OS 판정·최대 용량 %는 Windows에 없어 null."""
    if not battery.ok:
        return _skipped_battery("TOOL_ERROR"), None
    if not rows(battery.stdout):
        return {"status": "NO_BATTERY", "skippedReason": None, **dict.fromkeys(_SKIP_NULLS)}, None
    statics = rows(static.stdout) if static.ok else []
    reports = rows(report.stdout) if report is not None and report.ok else []
    design = _sum(statics, "DesignedCapacity") or _sum(reports, "DesignCapacity")
    full_mwh = _sum(rows(full.stdout) if full.ok else [], "FullChargedCapacity") or _sum(reports, "FullChargeCapacity")
    if design is None or full_mwh is None:
        denied = _denied(static) or _denied(full) or (report is not None and _denied(report))
        return _skipped_battery("NO_PERMISSION" if denied else "TOOL_ERROR"), None
    cycles = [_positive(c.get("CycleCount")) for c in (rows(cycle.stdout) if cycle.ok else [])]
    cycles += [_positive(r.get("CycleCount")) for r in reports]
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
    # BatteryStaticData가 실패하는 기기(갤럭시 북 등)는 배터리 리포트의 시리얼로 배터리 교체를 잡는다
    serial = _str(first.get("SerialNumber"), 64) or next(
        (s for r in reports if _real_serial(s := _str(r.get("SerialNumber"), 64))), "")
    return result, {"kind": "BATTERY", "identifier": name, "detail": {"serial": serial} if serial else {}}


def _needs_report(outs: dict[tuple[str, ...], Output]) -> bool:
    """배터리가 있는데 root/wmi에서 설계·완충 용량을 하나라도 못 읽었으면 배터리 리포트를 만든다(2초쯤 걸림)."""
    if not (outs[BATTERY].ok and rows(outs[BATTERY].stdout)):
        return False
    static, full = outs[BATTERY_STATIC], outs[BATTERY_FULL]
    return not (static.ok and _sum(rows(static.stdout), "DesignedCapacity")) or not (
        full.ok and _sum(rows(full.stdout), "FullChargedCapacity"))


def _remove_report() -> None:
    try:
        os.remove(os.path.join(tempfile.gettempdir(), REPORT_FILE))
    except OSError:
        pass


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


def parse_reliability(out: Output, disks: str) -> dict[str, Any]:
    """smartctl을 못 쓸 때 Get-StorageReliabilityCounter의 Wear(=사용률 %)·PowerOnHours. 예비·경고·미디어 오류는 주지 않아 null.
    PowerOnHours가 비면 Wear도 믿지 않는다."""
    def skipped(reason: str) -> dict[str, Any]:
        return {"status": "SKIPPED", "skippedReason": reason, **dict.fromkeys(_SSD_NULLS)}

    if not out.ok:
        return skipped("NO_PERMISSION" if _denied(out) else "TOOL_ERROR")
    counter = (rows(out.stdout) or [{}])[0]
    wear, hours = _int(counter.get("Wear")), _int(counter.get("PowerOnHours"))
    internal = [d for d in rows(disks) if _label(d.get("BusType"), _BUS) != "USB"]
    bus = _label(internal[0].get("BusType"), _BUS) if internal else None
    protocol = {"NVMe": "NVME", "SATA": "ATA"}.get(bus or "")
    # 가동 시간을 못 주는 드라이버는 Wear도 실제 값 대신 0을 채운다(갤럭시 북: smartctl 4%인데 Wear 0).
    # 가동 시간이 없으면 Wear를 믿지 않고 읽지 못함으로 둔다
    if protocol is None or hours is None:
        return skipped("UNSUPPORTED")
    return {"status": "OK", "skippedReason": None, "protocol": protocol,
            "percentageUsed": wear if wear is not None and 0 <= wear <= 255 else None, "availableSpare": None,
            "criticalWarning": None, "mediaErrors": None,
            "powerOnHours": hours if hours >= 0 else None}


def parse_checks(bitlocker: Output) -> dict[str, Any]:
    """반납·출고 전 경고(올리지 않고 요약에만). BitLocker가 켜져 있으면 복구 키 없이 디스크를 못 연다.
    관리자 권한이 없으면 읽지 못해 '모름'."""
    volumes = rows(bitlocker.stdout) if bitlocker.ok else []
    system = next((v for v in volumes if str(v.get("DriveLetter") or "").upper().startswith("C")), None)
    if system is None:
        return {"bitLocker": None, "warnings": []}
    on = _int(system.get("ProtectionStatus")) == 1
    warnings = ["BitLocker가 켜져 있어요. 복구 키가 회사 계정에 있는지 확인하고 초기화해 주세요"] if on else []
    return {"bitLocker": "켜짐" if on else "꺼짐", "warnings": warnings}


def _os_version() -> str:
    """Windows는 platform.version()이 빌드 번호(10.0.22631)다. 다른 OS에서 테스트할 때는 release로 대신한다."""
    version = platform.version() if sys.platform == "win32" else platform.release()
    return (version or "unknown")[:32]


def collect(run: Runner) -> dict[str, Any]:
    """고정 목록 명령을 돌려 진단 JSON 조각(벤치마크·시각 제외)을 만든다."""
    outs = {argv: run(argv) for argv in (SYSTEM, BIOS, CPU, MEMORY, DISKS, VIDEO, BATTERY, BATTERY_STATIC,
                                         BATTERY_FULL, BATTERY_CYCLE, BATTERY_STATUS, PROCESSES, UPTIME, SMARTCTL,
                                         BITLOCKER)}
    report = None
    if _needs_report(outs):
        outs[BATTERY_REPORT] = run(BATTERY_REPORT)
        report = outs[BATTERY_REPORT_READ] = run(BATTERY_REPORT_READ)
        _remove_report()
    smart = outs[SMARTCTL]
    if smart.code is None:  # PATH에 없으면 기본 설치 경로
        smart = outs[SMARTCTL_DEFAULT_PATH] = run(SMARTCTL_DEFAULT_PATH)

    def text(argv: tuple[str, ...]) -> str:
        return outs[argv].stdout if outs[argv].ok else ""

    storage = parse_storage(smart)
    if storage["skippedReason"] == "TOOL_ERROR":  # smartctl이 없거나 실패: Windows 기본 기능으로
        outs[RELIABILITY] = run(RELIABILITY)
        storage = parse_reliability(outs[RELIABILITY], text(DISKS))

    components = parse_cpu(text(CPU)) + parse_memory(text(MEMORY)) + parse_disks(text(DISKS))
    battery, battery_part = parse_battery(outs[BATTERY], outs[BATTERY_STATIC], outs[BATTERY_FULL], outs[BATTERY_CYCLE],
                                          report)
    if battery_part:
        components.append(battery_part)
    components += parse_video(text(VIDEO))
    return {
        "os": {"type": "WINDOWS", "version": _os_version(), "arch": platform.machine()},
        "device": parse_device(text(SYSTEM), text(BIOS)),
        "conditions": parse_conditions(text(BATTERY), text(BATTERY_STATUS), text(PROCESSES), text(UPTIME)),
        "components": components,
        "battery": battery,
        "storage": storage,
        "sources": [o.source for o in outs.values()],
        "checks": parse_checks(outs[BITLOCKER]),  # 요약에만 쓰고 올리지 않는다
    }
