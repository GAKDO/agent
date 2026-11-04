"""실행할 수 있는 명령의 고정 목록(NFR-02)과 실행 함수.

목록 밖 명령은 실행하지 않는다. 사용자 폴더·브라우저 기록을 읽는 명령은 목록에 없다.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

MACOS: tuple[tuple[str, ...], ...] = (
    ("system_profiler", "SPHardwareDataType", "-json"),
    ("system_profiler", "SPPowerDataType", "-json"),
    ("system_profiler", "SPNVMeDataType", "-json"),
    ("system_profiler", "SPDisplaysDataType", "-json"),
    ("ioreg", "-r", "-a", "-c", "AppleSmartBattery"),
    ("pmset", "-g", "batt"),
    ("pmset", "-g", "therm"),
    ("smartctl", "-j", "-a", "disk0"),
    ("ps", "-A", "-o", "pid="),
    ("sysctl", "-n", "kern.boottime"),
)


def _ps(script: str) -> tuple[str, ...]:
    return ("powershell", "-NoProfile", "-NonInteractive", "-Command", script)


# Windows(AG2): PowerShell은 고른 속성만 꺼낸다. Name·UserName·UUID는 Select-Object에 없다.
_JSON = " | ConvertTo-Json"
WINDOWS: dict[str, tuple[str, ...]] = {
    "SYSTEM": _ps("Get-CimInstance Win32_ComputerSystem | Select-Object Manufacturer,Model,SystemFamily" + _JSON),
    "BIOS": _ps("Get-CimInstance Win32_BIOS | Select-Object SerialNumber" + _JSON),
    "CPU": _ps("Get-CimInstance Win32_Processor | Select-Object Name,NumberOfCores,NumberOfLogicalProcessors" + _JSON),
    "MEMORY": _ps("Get-CimInstance Win32_PhysicalMemory | Select-Object Capacity" + _JSON),
    "DISKS": _ps("Get-PhysicalDisk | Select-Object FriendlyName,SerialNumber,Size,MediaType,BusType,HealthStatus" + _JSON),
    "VIDEO": _ps("Get-CimInstance Win32_VideoController | "
                 "Select-Object Name,CurrentHorizontalResolution,CurrentVerticalResolution" + _JSON),
    "BATTERY": _ps("Get-CimInstance Win32_Battery | Select-Object Name,EstimatedChargeRemaining,BatteryStatus" + _JSON),
    "BATTERY_STATIC": _ps("Get-CimInstance -Namespace root/wmi BatteryStaticData | "
                          "Select-Object DeviceName,SerialNumber,DesignedCapacity" + _JSON),
    "BATTERY_FULL": _ps("Get-CimInstance -Namespace root/wmi BatteryFullChargedCapacity | "
                        "Select-Object FullChargedCapacity" + _JSON),
    "BATTERY_CYCLE": _ps("Get-CimInstance -Namespace root/wmi BatteryCycleCount | Select-Object CycleCount" + _JSON),
    "BATTERY_STATUS": _ps("Get-CimInstance -Namespace root/wmi BatteryStatus | Select-Object PowerOnline" + _JSON),
    # BatteryStaticData가 "일반 오류"인 기기(갤럭시 북 등)는 Windows 배터리 리포트에서 같은 mWh 값을 읽는다
    "BATTERY_REPORT": _ps("powercfg /batteryreport /xml /output $env:TEMP\\trace-battery.xml | Out-Null"),
    "BATTERY_REPORT_READ": _ps("([xml](gc $env:TEMP\\trace-battery.xml)).BatteryReport.Batteries.Battery | "
                               "Select-Object DesignCapacity,FullChargeCapacity,CycleCount" + _JSON),
    "PROCESSES": _ps("(Get-Process).Count"),
    "UPTIME": _ps("[int]((Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime).TotalSeconds"),
    "SMARTCTL": ("smartctl", "-j", "-a", "/dev/sda"),
    "SMARTCTL_DEFAULT_PATH": (r"C:\Program Files\smartmontools\bin\smartctl.exe", "-j", "-a", "/dev/sda"),
}

ALLOWED: tuple[tuple[str, ...], ...] = MACOS + tuple(WINDOWS.values())


@dataclass(frozen=True)
class Output:
    argv: tuple[str, ...]
    code: int | None  # None = 명령이 없거나 시간 초과
    stdout: str
    stderr: str = ""

    @property
    def ok(self) -> bool:
        return self.code == 0

    @property
    def source(self) -> str:
        return " ".join(self.argv)


Runner = Callable[[tuple[str, ...]], Output]


class NotAllowed(Exception):
    """고정 목록 밖의 명령."""


def run(argv: tuple[str, ...], timeout: float = 60) -> Output:
    if argv not in ALLOWED:
        raise NotAllowed(" ".join(argv))
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout, check=False)
    except FileNotFoundError:
        return Output(argv, None, "", "명령 없음")
    except subprocess.TimeoutExpired:
        return Output(argv, None, "", "시간 초과")
    return Output(argv, done.returncode, done.stdout, done.stderr)
