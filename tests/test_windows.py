"""이 파일이 확인하는 것: 윈도우 진단 수집(요구사항 AG2).
실제 LG 그램·갤럭시 북에서 받아 둔 PowerShell 명령 출력(tests/fixtures/windows)으로 배터리·SSD·부품·
측정 조건을 읽고, 명령이 실패하거나 권한이 없을 때 어떻게 대신하는지 본다.

AG2 수용 시나리오: Windows 명령 출력 고정 파일(tests/fixtures/windows)로 확인.
"""

from __future__ import annotations

import json
from pathlib import Path

from trace_agent import report, windows
from trace_agent.__main__ import main
from trace_agent.commands import ALLOWED, Output

FIXTURES = Path(__file__).parent / "fixtures" / "windows"
# 윈도우 명령 → 실제 출력 파일 이름.
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


# 가짜 윈도우 명령 실행기. 허용 목록 밖 명령이 불리면 바로 테스트 실패. 파일이 없는 명령은 "명령 없음".
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


# 도우미: 수집 결과로 진단 문서를 만든다.
def _doc(collected: dict, benches: list | None = None) -> dict:
    reason = None if benches else ("NO_AC_POWER" if not collected["conditions"]["acPower"] else "TOOL_ERROR")
    return report.assemble(collected, agent_version="0.1.0", collected_at="2026-11-04T10:00:00+09:00",
                           consented_at="2026-11-04T10:00:00+09:00", benchmarks=benches or [],
                           benchmark_skipped_reason=reason)


# [상황] LG 그램 출력으로 진단한다.
# [기대] 스키마를 통과하고, OS는 WINDOWS, 기기 일련번호·제조사·모델이 정확하다.
def test_그램_출력으로_만든_진단은_스키마를_통과하고_OS는_WINDOWS다():
    collected = windows.collect(WinRunner())
    doc = _doc(collected)
    assert report.errors(doc) == []
    assert collected["os"]["type"] == "WINDOWS"
    assert collected["device"] == {"serial": "LGTEST00001", "manufacturer": "LG Electronics",
                                   "model": "16Z90R-GA7CK", "modelName": "LG gram"}


# [상황] 윈도우에서 배터리 정보를 읽는다.
# [기대] 설계 80000mWh·완충 74120mWh는 원래 단위(mWh) 그대로, 충전 87회.
#        윈도우는 맥처럼 "최대 용량 %·상태 판정"을 주지 않으므로 그 칸은 비운다.
def test_배터리_용량은_mWh_원값_그대로이고_OS_판정과_최대_용량은_null이다():
    battery = windows.collect(WinRunner())["battery"]
    assert battery == {"status": "OK", "skippedReason": None, "cycleCount": 87,
                       "designCapacity": {"value": 80000, "unit": "mWh"},
                       "fullChargeCapacity": {"value": 74120, "unit": "mWh"},
                       "osMaxCapacityPercent": None, "osCondition": None}


# [상황] 부품 목록을 만든다(USB 메모리·화면 없는 그래픽 어댑터가 함께 연결돼 있음).
# [기대] CPU·RAM·SSD·배터리·화면 5개만 남기고 USB 메모리 등은 뺀다. SSD 상세와 화면 해상도가 정확하다.
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


# [상황] 측정 조건을 읽는다.
# [기대] 충전기 연결·배터리 72%·프로세스 231개·가동 12600초. 윈도우는 발열 상태를 주지 않아 비운다.
def test_조건은_전원_잔량_프로세스_가동시간이고_발열은_null이다():
    assert windows.collect(WinRunner())["conditions"] == {
        "acPower": True, "batteryPercent": 72, "thermalState": None, "processCount": 231, "uptimeSec": 12600}


# [상황] SSD 건강 도구 smartctl이 정상으로 답한다.
# [기대] 사용률 2%·여유 100%·사용 1430시간 등을 따로 남긴다.
def test_smartctl_NVMe_로그를_따로_남긴다():
    assert windows.collect(WinRunner())["storage"] == {
        "status": "OK", "skippedReason": None, "protocol": "NVME", "percentageUsed": 2, "availableSpare": 100,
        "criticalWarning": 0, "mediaErrors": 0, "powerOnHours": 1430}


# [상황] 관리자 권한 없이 실행해 smartctl이 "접근 거부"로 실패한다.
# [기대] SSD는 "건너뜀(권한 없음)"이고 값은 모두 비운다.
def test_관리자_권한이_없으면_SSD는_NO_PERMISSION이고_값은_모두_null이다():
    denied = Output(windows.SMARTCTL, 2, json.dumps({"smartctl": {"exit_status": 2, "messages": [
        {"string": "Smartctl open device: /dev/sda failed: Access denied", "severity": "error"}]}}))
    storage = windows.collect(WinRunner({windows.SMARTCTL: denied}))["storage"]
    assert storage["status"] == "SKIPPED" and storage["skippedReason"] == "NO_PERMISSION"
    assert all(storage[k] is None for k in ("protocol", "percentageUsed", "availableSpare", "criticalWarning",
                                             "mediaErrors", "powerOnHours"))


# [상황] smartctl이 PATH에는 없지만 기본 설치 경로에는 있다. 다른 경우에는 둘 다 없다.
# [기대] 기본 경로의 것을 써서 정상으로 읽고 출처에 남긴다. 둘 다 없으면 "도구 오류".
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


# [상황] 배터리가 없는 윈도우 PC다.
# [기대] NO_BATTERY, 값 비움, 부품 목록에서 배터리 빠짐, 전원은 "연결됨"으로 본다.
def test_배터리가_없으면_NO_BATTERY이고_전원은_연결로_본다():
    runner = WinRunner({windows.BATTERY: Output(windows.BATTERY, 0, "")})
    collected = windows.collect(runner)
    assert collected["battery"]["status"] == "NO_BATTERY"
    assert all(v is None for k, v in collected["battery"].items() if k != "status")
    assert "BATTERY" not in [c["kind"] for c in collected["components"]]
    assert collected["conditions"]["acPower"] is True and collected["conditions"]["batteryPercent"] is None
    assert report.errors(_doc(collected)) == []


# [상황] 배터리 용량 명령이 "액세스 거부"로 실패한다. 다른 경우에는 "지원 안 함"으로 실패한다.
# [기대] 권한 문제면 NO_PERMISSION, 그 밖에는 TOOL_ERROR로 건너뛴다. 문서는 그래도 스키마를 통과한다.
def test_배터리_용량을_못_읽으면_SKIPPED이고_권한_오류면_NO_PERMISSION이다():
    failed = Output(windows.BATTERY_STATIC, 1, "", "Get-CimInstance : 액세스가 거부되었습니다.")
    battery = windows.collect(WinRunner({windows.BATTERY_STATIC: failed}))["battery"]
    assert battery["status"] == "SKIPPED" and battery["skippedReason"] == "NO_PERMISSION"

    empty = Output(windows.BATTERY_FULL, 1, "", "Not supported")
    collected = windows.collect(WinRunner({windows.BATTERY_FULL: empty}))
    assert collected["battery"]["skippedReason"] == "TOOL_ERROR"
    assert report.errors(_doc(collected)) == []


# [상황] 충전 횟수가 0이거나 명령이 실패한다.
# [기대] 둘 다 "모름(null)".
def test_사이클을_모르면_null이고_0도_null이다():
    zero = Output(windows.BATTERY_CYCLE, 0, '{"CycleCount": 0}')
    assert windows.collect(WinRunner({windows.BATTERY_CYCLE: zero}))["battery"]["cycleCount"] is None
    failed = Output(windows.BATTERY_CYCLE, 1, "", "Not supported")
    assert windows.collect(WinRunner({windows.BATTERY_CYCLE: failed}))["battery"]["cycleCount"] is None


# [상황] 전원 연결 여부 명령이 실패한다.
# [기대] 배터리 상태 값으로 대신 판단한다(상태 1 = 배터리 사용 중 → 충전기 없음, 잔량 40%).
def test_PowerOnline을_못_읽으면_Win32_Battery_상태로_전원을_정한다():
    failed = Output(windows.BATTERY_STATUS, 1, "", "Not supported")
    on_battery = Output(windows.BATTERY, 0, '{"Name": "LGC 80Wh", "EstimatedChargeRemaining": 40, "BatteryStatus": 1}')
    assert windows.collect(WinRunner({windows.BATTERY_STATUS: failed}))["conditions"]["acPower"] is True
    off = windows.collect(WinRunner({windows.BATTERY_STATUS: failed, windows.BATTERY: on_battery}))["conditions"]
    assert off["acPower"] is False and off["batteryPercent"] == 40


# [상황] 기기 일련번호가 "To be filled by O.E.M."(제조사가 안 채운 자리표시)이다.
# [기대] 빈 값으로 두어 스키마 검사에서 "device/serial" 오류로 걸리게 한다(가짜 번호로 올리지 않음).
def test_OEM_자리표시_시리얼은_빈_값으로_두어_스키마에서_걸린다():
    bios = Output(windows.BIOS, 0, '{"SerialNumber": "To be filled by O.E.M."}')
    collected = windows.collect(WinRunner({windows.BIOS: bios}))
    assert collected["device"]["serial"] == ""
    assert any(e.startswith("device/serial") for e in report.errors(_doc(collected)))


# [상황] 윈도우에서 실행하는 명령 문장을 모두 살핀다.
# [기대] 사용자 이름·UUID·컴퓨터 이름·도메인을 꺼내는 부분이 없고, 출처 문장은 계약 한도 200자 안이다.
def test_윈도우_명령은_컴퓨터_이름_사용자_이름_UUID를_꺼내지_않고_출처_길이는_계약_안이다():
    collected = windows.collect(WinRunner())
    for argv in windows.WINDOWS.values():
        script = " ".join(argv)
        for word in ("UserName", "UUID", "DNSHostName", "CSName", "Domain", "-Property *", "Select-Object *"):
            assert word not in script
    assert "Name" not in " ".join(windows.SYSTEM)  # Win32_ComputerSystem.Name = 컴퓨터 이름
    assert all(len(s) <= 200 for s in collected["sources"])
    assert all(len(" ".join(argv)) <= 200 for argv in windows.WINDOWS.values())  # 계약: sources 항목 200자


# [상황] 윈도우 컴퓨터에서 에이전트를 실행한다.
# [기대] 윈도우 수집기로 진단하고(용량 단위 mWh), 화면 요약에 "발열 모름"이 보인다.
def test_win32에서는_윈도우_수집기로_진단한다(tmp_path, capsys):
    out = tmp_path / "d.json"
    code = main(["run", "--out", str(out)], env={}, run=WinRunner(), system="win32",
                workloads={"CPU_SINGLE": ("ops/s", lambda: 1.0)},
                clock=lambda: "2026-11-04T10:00:00+09:00")
    doc = json.loads(out.read_text(encoding="utf-8"))
    printed = capsys.readouterr().out
    assert doc["os"]["type"] == "WINDOWS" and doc["battery"]["designCapacity"]["unit"] == "mWh"
    assert "발열 모름" in printed and code == 0


# 갤럭시 북에서 실제로 본 "일반 오류" 메시지.
GENERAL_ERROR = "Get-CimInstance : 일반 오류입니다.\n    + FullyQualifiedErrorId : HRESULT 0x80041001"


# [상황] 갤럭시 북처럼 배터리 정보 명령이 "일반 오류"로 실패한다.
# [기대] 배터리 리포트(powercfg /batteryreport)를 만들어 설계 용량 66990mWh·충전 317회를 채운다.
#        완충 용량은 다른 명령으로 읽힌 값(74120)을 쓰고, 문서는 스키마를 통과한다.
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
    assert battery["designCapacity"] == {"value": 66990, "unit": "mWh"}  # 리포트 값(갤럭시 북 실기)
    assert battery["fullChargeCapacity"] == {"value": 74120, "unit": "mWh"}  # root/wmi 값이 있으면 그것
    assert battery["cycleCount"] == 317
    assert ("BATTERY", "LGC 80Wh") in [(c["kind"], c["identifier"]) for c in collected["components"]]
    assert " ".join(windows.BATTERY_REPORT) in collected["sources"]
    assert report_error_free(collected)


# [상황] 배터리 정보가 기본 명령으로 다 읽힌다.
# [기대] 시간이 걸리는 배터리 리포트는 만들지 않는다.
def test_root_wmi로_다_읽히면_배터리_리포트를_만들지_않는다():
    runner = WinRunner()
    windows.collect(runner)
    assert windows.BATTERY_REPORT not in runner.calls


# [상황] 기본 명령도 배터리 리포트도 모두 실패한다.
# [기대] 배터리는 "도구 오류"로 건너뛴다.
def test_배터리_리포트도_실패하면_TOOL_ERROR다():
    runner = WinRunner({
        windows.BATTERY_STATIC: Output(windows.BATTERY_STATIC, 1, "", GENERAL_ERROR),
        windows.BATTERY_REPORT: Output(windows.BATTERY_REPORT, 1, "", "오류"),
        windows.BATTERY_REPORT_READ: Output(windows.BATTERY_REPORT_READ, 1, "", "경로를 찾을 수 없습니다"),
    })
    assert windows.collect(runner)["battery"]["skippedReason"] == "TOOL_ERROR"


def report_error_free(collected: dict) -> bool:
    return report.errors(_doc(collected)) == []


# smartctl이 설치돼 있지 않은 상황.
MISSING_SMART = {windows.SMARTCTL: Output(windows.SMARTCTL, None, "", "명령 없음")}


# [상황] smartctl이 없다.
# [기대] 윈도우 기본 기능(Get-StorageReliabilityCounter)으로 SSD 마모도 4%·사용 6252시간을 읽는다.
def test_smartctl이_없으면_Windows_기본_기능으로_마모도와_가동_시간을_읽는다():
    runner = WinRunner({**MISSING_SMART, windows.RELIABILITY: Output(windows.RELIABILITY, 0,
                                                                     '{"Wear": 4, "PowerOnHours": 6252}')})
    collected = windows.collect(runner)
    assert collected["storage"] == {"status": "OK", "skippedReason": None, "protocol": "NVME", "percentageUsed": 4,
                                    "availableSpare": None, "criticalWarning": None, "mediaErrors": None,
                                    "powerOnHours": 6252}
    assert " ".join(windows.RELIABILITY) in collected["sources"]
    assert report_error_free(collected)


# [상황] smartctl이 정상으로 된다.
# [기대] 윈도우 기본 기능은 부르지 않는다.
def test_smartctl이_되면_기본_기능은_부르지_않는다():
    runner = WinRunner()
    windows.collect(runner)
    assert windows.RELIABILITY not in runner.calls


# [상황] 기본 기능도 권한이 없거나, 값이 비어 있다.
# [기대] 권한 없음이면 NO_PERMISSION, 값이 없으면 UNSUPPORTED(이 기기는 지원 안 함).
def test_기본_기능도_권한이_없으면_NO_PERMISSION_값이_없으면_UNSUPPORTED다():
    denied = Output(windows.RELIABILITY, 1, "", "Get-StorageReliabilityCounter : Access denied")
    assert windows.collect(WinRunner({**MISSING_SMART, windows.RELIABILITY: denied}))["storage"]["skippedReason"] \
        == "NO_PERMISSION"
    empty = Output(windows.RELIABILITY, 0, '{"Wear": null, "PowerOnHours": null}')
    collected = windows.collect(WinRunner({**MISSING_SMART, windows.RELIABILITY: empty}))
    assert collected["storage"]["skippedReason"] == "UNSUPPORTED"
    assert report_error_free(collected)


# [상황] 기본 기능이 사용 시간 없이 마모도 0만 준다(갤럭시 북 실측: 실제로는 4%였음).
# [기대] 믿을 수 없는 값이라 쓰지 않고 UNSUPPORTED로 건너뛴다.
def test_기본_기능이_가동_시간_없이_Wear_0만_주면_믿지_않고_UNSUPPORTED다():
    # 갤럭시 북 실측: smartctl은 사용률 4%인데 Get-StorageReliabilityCounter는 Wear 0, PowerOnHours 빈칸
    zero = Output(windows.RELIABILITY, 0, '{"Wear": 0, "PowerOnHours": null}')
    collected = windows.collect(WinRunner({**MISSING_SMART, windows.RELIABILITY: zero}))
    assert collected["storage"]["status"] == "SKIPPED"
    assert collected["storage"]["skippedReason"] == "UNSUPPORTED"
    assert collected["storage"]["percentageUsed"] is None
    assert report_error_free(collected)


# [상황] 배터리 조회 결과는 비었는데 전원 연결 여부는 "아님(false)"이다.
# [기대] 충전기가 없는 것으로 본다.
def test_배터리_조회가_비어도_PowerOnline이_false면_전원_없음으로_본다() -> None:
    status = json.dumps([{"PowerOnline": False}])
    assert windows.parse_conditions("", status, "100", "60")["acPower"] is False
