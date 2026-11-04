"""AG2 수용 시나리오: Windows 명령 출력 고정 파일(tests/fixtures/windows)로 확인."""

from __future__ import annotations

import json
from pathlib import Path

from trace_agent import report, windows
from trace_agent.__main__ import main
from trace_agent.commands import ALLOWED, Output

FIXTURES = Path(__file__).parent / "fixtures" / "windows"
FILES = {
    windows.SYSTEM: "system.json",
    windows.BIOS: "bios.json",
    windows.CPU: "cpu.json",
    windows.MEMORY: "memory.json",
    windows.DISKS: "disks.json",
    windows.VIDEO: "video.json",
    windows.BATTERY: "battery.json",
    windows.BATTERY_STATIC: "battery_static.json",
    windows.BATTERY_FULL: "battery_full.json",
    windows.BATTERY_CYCLE: "battery_cycle.json",
    windows.BATTERY_STATUS: "battery_status.json",
    windows.PROCESSES: "processes.txt",
    windows.UPTIME: "uptime.txt",
    windows.SMARTCTL: "smartctl.json",
}


class WinRunner:
    def __init__(self, overrides: dict[tuple[str, ...], Output] | None = None) -> None:
        self.overrides = overrides or {}
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: tuple[str, ...]) -> Output:
        assert argv in ALLOWED
        self.calls.append(argv)
        if argv in self.overrides:
            return self.overrides[argv]
        if argv not in FILES:
            return Output(argv, None, "", "명령 없음")
        return Output(argv, 0, (FIXTURES / FILES[argv]).read_text(encoding="utf-8"))


def _doc(collected: dict, benches: list | None = None) -> dict:
    reason = None if benches else ("NO_AC_POWER" if not collected["conditions"]["acPower"] else "TOOL_ERROR")
    return report.assemble(collected, agent_version="0.1.0", collected_at="2026-11-04T10:00:00+09:00",
                           consented_at="2026-11-04T10:00:00+09:00", benchmarks=benches or [],
                           benchmark_skipped_reason=reason)


def test_그램_출력으로_만든_진단은_스키마를_통과하고_OS는_WINDOWS다():
    collected = windows.collect(WinRunner())
    doc = _doc(collected)
    assert report.errors(doc) == []
    assert collected["os"]["type"] == "WINDOWS"
    assert collected["device"] == {"serial": "LGTEST00001", "manufacturer": "LG Electronics",
                                   "model": "16Z90R-GA7CK", "modelName": "LG gram"}


def test_배터리_용량은_mWh_원값_그대로이고_OS_판정과_최대_용량은_null이다():
    battery = windows.collect(WinRunner())["battery"]
    assert battery == {"status": "OK", "skippedReason": None, "cycleCount": 87,
                       "designCapacity": {"value": 80000, "unit": "mWh"},
                       "fullChargeCapacity": {"value": 74120, "unit": "mWh"},
                       "osMaxCapacityPercent": None, "osCondition": None}


def test_부품은_CPU_RAM_SSD_배터리_화면이고_USB_메모리와_화면_없는_어댑터는_뺀다():
    components = windows.collect(WinRunner())["components"]
    assert [(c["kind"], c["identifier"]) for c in components] == [
        ("CPU", "13th Gen Intel(R) Core(TM) i7-1360P"),
        ("RAM", "16 GB"),
        ("SSD", "SAMSUNG MZVL2512HCJQ-00B00"),
        ("BATTERY", "LGC 80Wh"),
        ("DISPLAY", "Intel(R) Iris(R) Xe Graphics"),
    ]
    assert components[2]["detail"] == {"serial": "SSDTEST01", "capacityBytes": 512110190592, "busType": "NVMe",
                                       "mediaType": "SSD", "health": "Healthy"}
    assert components[4]["detail"] == {"resolution": "2560x1600"}


def test_조건은_전원_잔량_프로세스_가동시간이고_발열은_null이다():
    assert windows.collect(WinRunner())["conditions"] == {
        "acPower": True, "batteryPercent": 72, "thermalState": None, "processCount": 231, "uptimeSec": 12600}


def test_smartctl_NVMe_로그를_따로_남긴다():
    assert windows.collect(WinRunner())["storage"] == {
        "status": "OK", "skippedReason": None, "protocol": "NVME", "percentageUsed": 2, "availableSpare": 100,
        "criticalWarning": 0, "mediaErrors": 0, "powerOnHours": 1430}


def test_관리자_권한이_없으면_SSD는_NO_PERMISSION이고_값은_모두_null이다():
    denied = Output(windows.SMARTCTL, 2, json.dumps({"smartctl": {"exit_status": 2, "messages": [
        {"string": "Smartctl open device: /dev/sda failed: Access denied", "severity": "error"}]}}))
    storage = windows.collect(WinRunner({windows.SMARTCTL: denied}))["storage"]
    assert storage["status"] == "SKIPPED" and storage["skippedReason"] == "NO_PERMISSION"
    assert all(storage[k] is None for k in ("protocol", "percentageUsed", "availableSpare", "criticalWarning",
                                             "mediaErrors", "powerOnHours"))


def test_smartctl이_PATH에_없으면_기본_설치_경로를_쓰고_둘_다_없으면_TOOL_ERROR다():
    missing = Output(windows.SMARTCTL, None, "", "명령 없음")
    text = (FIXTURES / "smartctl.json").read_text(encoding="utf-8")
    runner = WinRunner({windows.SMARTCTL: missing,
                        windows.SMARTCTL_DEFAULT_PATH: Output(windows.SMARTCTL_DEFAULT_PATH, 0, text)})
    collected = windows.collect(runner)
    assert collected["storage"]["status"] == "OK"
    assert " ".join(windows.SMARTCTL_DEFAULT_PATH) in collected["sources"]

    neither = windows.collect(WinRunner({windows.SMARTCTL: missing}))
    assert neither["storage"]["skippedReason"] == "TOOL_ERROR"


def test_배터리가_없으면_NO_BATTERY이고_전원은_연결로_본다():
    runner = WinRunner({windows.BATTERY: Output(windows.BATTERY, 0, "")})
    collected = windows.collect(runner)
    assert collected["battery"]["status"] == "NO_BATTERY"
    assert all(v is None for k, v in collected["battery"].items() if k != "status")
    assert "BATTERY" not in [c["kind"] for c in collected["components"]]
    assert collected["conditions"]["acPower"] is True and collected["conditions"]["batteryPercent"] is None
    assert report.errors(_doc(collected)) == []


def test_배터리_용량을_못_읽으면_SKIPPED이고_권한_오류면_NO_PERMISSION이다():
    failed = Output(windows.BATTERY_STATIC, 1, "", "Get-CimInstance : 액세스가 거부되었습니다.")
    battery = windows.collect(WinRunner({windows.BATTERY_STATIC: failed}))["battery"]
    assert battery["status"] == "SKIPPED" and battery["skippedReason"] == "NO_PERMISSION"

    empty = Output(windows.BATTERY_FULL, 1, "", "Not supported")
    collected = windows.collect(WinRunner({windows.BATTERY_FULL: empty}))
    assert collected["battery"]["skippedReason"] == "TOOL_ERROR"
    assert report.errors(_doc(collected)) == []


def test_사이클을_모르면_null이고_0도_null이다():
    zero = Output(windows.BATTERY_CYCLE, 0, '{"CycleCount": 0}')
    assert windows.collect(WinRunner({windows.BATTERY_CYCLE: zero}))["battery"]["cycleCount"] is None
    failed = Output(windows.BATTERY_CYCLE, 1, "", "Not supported")
    assert windows.collect(WinRunner({windows.BATTERY_CYCLE: failed}))["battery"]["cycleCount"] is None


def test_PowerOnline을_못_읽으면_Win32_Battery_상태로_전원을_정한다():
    failed = Output(windows.BATTERY_STATUS, 1, "", "Not supported")
    on_battery = Output(windows.BATTERY, 0, '{"Name": "LGC 80Wh", "EstimatedChargeRemaining": 40, "BatteryStatus": 1}')
    assert windows.collect(WinRunner({windows.BATTERY_STATUS: failed}))["conditions"]["acPower"] is True
    off = windows.collect(WinRunner({windows.BATTERY_STATUS: failed, windows.BATTERY: on_battery}))["conditions"]
    assert off["acPower"] is False and off["batteryPercent"] == 40


def test_OEM_자리표시_시리얼은_빈_값으로_두어_스키마에서_걸린다():
    bios = Output(windows.BIOS, 0, '{"SerialNumber": "To be filled by O.E.M."}')
    collected = windows.collect(WinRunner({windows.BIOS: bios}))
    assert collected["device"]["serial"] == ""
    assert any(e.startswith("device/serial") for e in report.errors(_doc(collected)))


def test_윈도우_명령은_컴퓨터_이름_사용자_이름_UUID를_꺼내지_않고_출처_길이는_계약_안이다():
    collected = windows.collect(WinRunner())
    for argv in windows.WINDOWS.values():
        script = " ".join(argv)
        for word in ("UserName", "UUID", "DNSHostName", "CSName", "Domain", "-Property *", "Select-Object *"):
            assert word not in script
    assert "Name" not in " ".join(windows.SYSTEM)  # Win32_ComputerSystem.Name = 컴퓨터 이름
    assert all(len(s) <= 200 for s in collected["sources"])


def test_win32에서는_윈도우_수집기로_진단한다(tmp_path, capsys):
    out = tmp_path / "d.json"
    code = main(["run", "--out", str(out)], env={}, run=WinRunner(), system="win32",
                workloads={"CPU_SINGLE": ("ops/s", lambda: 1.0)},
                clock=lambda: "2026-11-04T10:00:00+09:00")
    doc = json.loads(out.read_text(encoding="utf-8"))
    printed = capsys.readouterr().out
    assert doc["os"]["type"] == "WINDOWS" and doc["battery"]["designCapacity"]["unit"] == "mWh"
    assert "발열 모름" in printed and code == 0


GENERAL_ERROR = "Get-CimInstance : 일반 오류입니다.\n    + FullyQualifiedErrorId : HRESULT 0x80041001"


def test_BatteryStaticData가_일반_오류면_배터리_리포트의_mWh로_채운다():
    report = (FIXTURES / "battery_report.json").read_text(encoding="utf-8")
    runner = WinRunner({
        windows.BATTERY_STATIC: Output(windows.BATTERY_STATIC, 1, "", GENERAL_ERROR),
        windows.BATTERY_CYCLE: Output(windows.BATTERY_CYCLE, 1, "", GENERAL_ERROR),
        windows.BATTERY_REPORT: Output(windows.BATTERY_REPORT, 0, ""),
        windows.BATTERY_REPORT_READ: Output(windows.BATTERY_REPORT_READ, 0, report),
    })
    collected = windows.collect(runner)
    battery = collected["battery"]
    assert battery["status"] == "OK"
    assert battery["designCapacity"] == {"value": 54000, "unit": "mWh"}  # 리포트 값
    assert battery["fullChargeCapacity"] == {"value": 74120, "unit": "mWh"}  # root/wmi 값이 있으면 그것
    assert battery["cycleCount"] == 212
    assert ("BATTERY", "LGC 80Wh") in [(c["kind"], c["identifier"]) for c in collected["components"]]
    assert " ".join(windows.BATTERY_REPORT) in collected["sources"]
    assert report_error_free(collected)


def test_root_wmi로_다_읽히면_배터리_리포트를_만들지_않는다():
    runner = WinRunner()
    windows.collect(runner)
    assert windows.BATTERY_REPORT not in runner.calls


def test_배터리_리포트도_실패하면_TOOL_ERROR다():
    runner = WinRunner({
        windows.BATTERY_STATIC: Output(windows.BATTERY_STATIC, 1, "", GENERAL_ERROR),
        windows.BATTERY_REPORT: Output(windows.BATTERY_REPORT, 1, "", "오류"),
        windows.BATTERY_REPORT_READ: Output(windows.BATTERY_REPORT_READ, 1, "", "경로를 찾을 수 없습니다"),
    })
    assert windows.collect(runner)["battery"]["skippedReason"] == "TOOL_ERROR"


def report_error_free(collected: dict) -> bool:
    return report.errors(_doc(collected)) == []
