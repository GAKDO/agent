"""반납 점검 보강(11/7): 잠금 상태 경고, 외부 모니터 제외, Windows RAM·배터리 시리얼."""

from __future__ import annotations

import json

from conftest import FIXTURES, FixtureRunner
from test_windows import WinRunner

from trace_agent import macos, report, windows
from trace_agent.commands import Output

HARDWARE = (FIXTURES / "hardware.json").read_text(encoding="utf-8")
LOCKED = HARDWARE.replace("activation_lock_disabled", "activation_lock_enabled")


def _doc(collected: dict) -> dict:
    return report.assemble(collected, agent_version="0.1.0", collected_at="2026-11-07T10:00:00+09:00",
                           consented_at="2026-11-07T10:00:00+09:00", benchmarks=[],
                           benchmark_skipped_reason="NO_AC_POWER")


def test_활성화_잠금이_켜져_있으면_요약에_경고가_보이고_올리는_JSON에는_들어가지_않는다():
    collected = macos.collect(FixtureRunner({macos.HARDWARE: Output(macos.HARDWARE, 0, LOCKED)}))
    doc = _doc(collected)
    text = report.summary(doc, collected["checks"])
    assert "활성화 잠금 켜짐" in text and "[주의] 활성화 잠금" in text
    assert report.errors(doc) == [] and "checks" not in doc and "활성화" not in json.dumps(doc, ensure_ascii=False)


def test_잠금이_모두_꺼져_있으면_경고_없이_꺼짐만_보인다(runner):
    collected = macos.collect(runner)
    assert collected["checks"] == {"activationLock": "꺼짐", "fileVault": "꺼짐", "warnings": []}
    assert "잠금(올리지 않음): 활성화 잠금 꺼짐, FileVault 꺼짐" in report.summary(_doc(collected), collected["checks"])


def test_FileVault가_켜져_있으면_경고하고_못_읽으면_모름이다():
    on = macos.collect(FixtureRunner({macos.FILEVAULT: Output(macos.FILEVAULT, 0, "FileVault is On.\n")}))
    assert on["checks"]["fileVault"] == "켜짐" and any("FileVault" in w for w in on["checks"]["warnings"])
    missing = macos.collect(FixtureRunner({macos.FILEVAULT: Output(macos.FILEVAULT, None, "", "명령 없음")}))
    assert missing["checks"]["fileVault"] is None


def test_OS가_본_SSD_SMART가_Verified가_아니면_경고한다():
    nvme = (FIXTURES / "nvme.json").read_text(encoding="utf-8").replace('"Verified"', '"Failing"')
    checks = macos.collect(FixtureRunner({macos.NVME: Output(macos.NVME, 0, nvme)}))["checks"]
    assert any("Failing" in w for w in checks["warnings"])


def test_smartctl이_없어도_요약에_OS_SMART_상태를_보인다(runner):
    collected = macos.collect(runner)
    assert "SSD: 생략 (사유 TOOL_ERROR), OS SMART 상태 Verified" in report.summary(_doc(collected))


def test_외부_모니터는_부품에서_빼서_부품_변경으로_잘못_플래그되지_않는다():
    data = json.loads((FIXTURES / "displays.json").read_text(encoding="utf-8"))
    data["SPDisplaysDataType"][0]["spdisplays_ndrvs"].append(
        {"_name": "DELL U2720Q", "_spdisplays_pixels": "3840 x 2160", "spdisplays_connection_type": "spdisplays_dp"})
    displays = macos.parse_displays(json.dumps(data))
    assert [d["identifier"] for d in displays] == ["Color LCD"]


def test_윈도우_RAM은_모듈_시리얼을_모아_같은_용량_교체도_잡고_00000000은_뺀다():
    memory = json.dumps([{"Capacity": 8589934592, "SerialNumber": "B2C3", "PartNumber": "M425R1GB4BB0"},
                         {"Capacity": 8589934592, "SerialNumber": "A1B2", "PartNumber": "M425R1GB4BB0"},
                         {"Capacity": 8589934592, "SerialNumber": "00000000", "PartNumber": ""}])
    ram = windows.parse_memory(memory)[0]
    assert ram["identifier"] == "24 GB"
    assert ram["detail"] == {"totalBytes": 3 * 8589934592, "modules": 3, "serial": "A1B2,B2C3",
                             "partNumber": "M425R1GB4BB0"}


def test_BatteryStaticData가_실패하면_배터리_리포트의_시리얼로_배터리_교체를_잡는다():
    fail = Output(windows.BATTERY_STATIC, 1, "", "일반 오류")
    report_read = Output(windows.BATTERY_REPORT_READ, 0, json.dumps(
        {"DesignCapacity": "66990", "FullChargeCapacity": "47740", "CycleCount": "317", "SerialNumber": "SN-GB-01"}))
    collected = windows.collect(WinRunner({windows.BATTERY_STATIC: fail, windows.BATTERY_REPORT: Output(
        windows.BATTERY_REPORT, 0, ""), windows.BATTERY_REPORT_READ: report_read}))
    battery = next(c for c in collected["components"] if c["kind"] == "BATTERY")
    assert battery["detail"] == {"serial": "SN-GB-01"}


def test_BitLocker가_켜져_있으면_경고하고_관리자_권한이_없으면_모름이다():
    on = Output(windows.BITLOCKER, 0, json.dumps([{"DriveLetter": "C:", "ProtectionStatus": 1},
                                                  {"DriveLetter": "D:", "ProtectionStatus": 0}]))
    checks = windows.collect(WinRunner({windows.BITLOCKER: on}))["checks"]
    assert checks["bitLocker"] == "켜짐" and len(checks["warnings"]) == 1
    denied = windows.collect(WinRunner())["checks"]  # 고정 파일 없음 = 권한 없음과 같다
    assert denied == {"bitLocker": None, "warnings": []}
    assert "BitLocker 모름" in report.summary(_doc(windows.collect(WinRunner())), denied)


def test_동의_전_요약에_올라가는_부품_시리얼과_부품_번호가_보인다():
    collected = windows.collect(WinRunner({windows.MEMORY: Output(windows.MEMORY, 0, json.dumps(
        [{"Capacity": 8589934592, "SerialNumber": "A1B2", "PartNumber": "M425R1GB4BB0"}]))}))
    text = report.summary(_doc(collected))
    assert "RAM serial A1B2 partNumber M425R1GB4BB0" in text and "SSD serial SSDTEST01" in text
