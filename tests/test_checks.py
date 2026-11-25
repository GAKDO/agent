"""이 파일이 확인하는 것: 반납 점검 보강(11/7 추가).
- 활성화 잠금·FileVault·BitLocker(디스크 암호화)가 켜져 있으면 경고: 반납 뒤 다음 사람이 못 쓰는 일을 막는다.
- 외부 모니터는 부품에서 빼서, 모니터를 꽂았다고 "부품이 바뀜"으로 잘못 걸리지 않게 한다.
- 윈도우 RAM·배터리 일련번호를 읽어 같은 용량으로 몰래 바꿔 끼운 것도 잡는다.
경고 문장은 고객 화면에만 보이고, 서버에는 ON/OFF 같은 코드 값만 올린다.

반납 점검 보강(11/7): 잠금 상태 경고, 외부 모니터 제외, Windows RAM·배터리 시리얼.
"""

from __future__ import annotations

import json

from conftest import FIXTURES, FixtureRunner
from test_windows import WinRunner

from trace_agent import macos, report, windows
from trace_agent.commands import Output

# 실제 맥 하드웨어 출력과, 그중 "활성화 잠금 켜짐"으로 바꾼 출력.
HARDWARE = (FIXTURES / "hardware.json").read_text(encoding="utf-8")
LOCKED = HARDWARE.replace("activation_lock_disabled", "activation_lock_enabled")


# 도우미: 수집한 값으로 진단 문서를 만든다(벤치마크는 건너뜀).
def _doc(collected: dict) -> dict:
    return report.assemble(collected, agent_version="0.1.0", collected_at="2026-11-07T10:00:00+09:00",
                           consented_at="2026-11-07T10:00:00+09:00", benchmarks=[],
                           benchmark_skipped_reason="NO_AC_POWER")


# [상황] 반납하는 맥의 "나의 찾기" 활성화 잠금이 켜져 있다.
# [기대] 요약에 "[주의] 활성화 잠금" 경고가 보이고, 서버에는 activationLock ON 코드만 올라간다(경고 문장은 안 올림).
def test_활성화_잠금이_켜져_있으면_요약에_경고가_보이고_올리는_JSON에는_코드_값으로_들어간다():
    collected = macos.collect(FixtureRunner({macos.HARDWARE: Output(macos.HARDWARE, 0, LOCKED)}))
    doc = _doc(collected)
    text = report.summary(doc, collected["checks"])
    assert "활성화 잠금 켜짐" in text and "[주의] 활성화 잠금" in text
    assert report.errors(doc) == [] and doc["checks"]["activationLock"] == "ON"
    assert "활성화" not in json.dumps(doc, ensure_ascii=False)  # 경고 문장은 올리지 않는다


# [상황] 활성화 잠금·FileVault 모두 꺼져 있고 SSD·보안 상태도 정상이다.
# [기대] 경고 없이 "꺼짐"만 보이고, 서버에는 OFF·OK·ON 코드 값으로 올라간다.
def test_잠금이_모두_꺼져_있으면_경고_없이_꺼짐만_보인다(runner):
    collected = macos.collect(runner)
    assert collected["checks"] == {"activationLock": "꺼짐", "fileVault": "꺼짐", "osDiskHealth": "OK",
                                   "security": "켜짐", "threatCount": None, "warnings": []}
    doc = _doc(collected)
    assert "잠금: 활성화 잠금 꺼짐, FileVault 꺼짐" in report.summary(doc, collected["checks"])
    assert doc["checks"] == {"activationLock": "OFF", "diskEncryption": "OFF", "osDiskHealth": "OK",
                             "securityProtection": "ON"}


# [상황] 디스크 암호화(FileVault)가 켜져 있다. 다른 경우에는 확인 명령이 없다.
# [기대] 켜져 있으면 경고, 읽지 못하면 "모름"으로 둔다.
def test_FileVault가_켜져_있으면_경고하고_못_읽으면_모름이다():
    on = macos.collect(FixtureRunner({macos.FILEVAULT: Output(macos.FILEVAULT, 0, "FileVault is On.\n")}))
    assert on["checks"]["fileVault"] == "켜짐" and any("FileVault" in w for w in on["checks"]["warnings"])
    missing = macos.collect(FixtureRunner({macos.FILEVAULT: Output(macos.FILEVAULT, None, "", "명령 없음")}))
    assert missing["checks"]["fileVault"] is None


# [상황] 맥이 SSD 상태를 Verified(정상)가 아닌 Failing(고장 징후)으로 알려 준다.
# [기대] 경고를 보여 주고 서버에는 osDiskHealth WARNING으로 올린다.
def test_OS가_본_SSD_SMART가_Verified가_아니면_경고한다():
    nvme = (FIXTURES / "nvme.json").read_text(encoding="utf-8").replace('"Verified"', '"Failing"')
    collected = macos.collect(FixtureRunner({macos.NVME: Output(macos.NVME, 0, nvme)}))
    assert any("Failing" in w for w in collected["checks"]["warnings"])
    doc = _doc(collected)
    assert doc["checks"]["osDiskHealth"] == "WARNING" and report.errors(doc) == []


# [상황] 하드웨어·FileVault·SSD·보안 명령을 모두 읽지 못했다.
# [기대] 올리는 점검 칸은 모두 "모름(null)"이고, 그래도 점검 칸에서는 스키마 오류가 나지 않는다.
def test_잠금_상태를_못_읽으면_올리는_checks는_모두_null이다():
    failed = {cmd: Output(cmd, None, "", "명령 없음")
              for cmd in (macos.HARDWARE, macos.FILEVAULT, macos.NVME, macos.GATEKEEPER, macos.SIP)}
    collected = macos.collect(FixtureRunner(failed))
    doc = _doc(collected)
    assert doc["checks"] == {"activationLock": None, "diskEncryption": None, "osDiskHealth": None}
    # 하드웨어 정보도 못 읽어 device가 비므로 checks 칸만 따로 확인한다
    assert not [e for e in report.errors(doc) if e.startswith("checks")]


# [상황] 윈도우에서 BitLocker가 켜져 있다.
# [기대] 디스크 암호화 ON으로 올리고, 맥에만 있는 활성화 잠금은 null로 둔다.
def test_윈도우는_BitLocker를_디스크_암호화로_올리고_활성화_잠금은_null이다():
    assert report.upload_checks({"bitLocker": "켜짐", "warnings": []}) == {
        "activationLock": None, "diskEncryption": "ON", "osDiskHealth": None}


# [상황] SSD 건강 도구가 없는 맥이다.
# [기대] 요약에 "SSD: 생략"과 함께 맥이 직접 본 SMART 상태(Verified)는 보여 준다.
def test_smartctl이_없어도_요약에_OS_SMART_상태를_보인다(runner):
    collected = macos.collect(runner)
    assert "SSD: 생략 (사유 TOOL_ERROR), OS SMART 상태 Verified" in report.summary(_doc(collected))


# [상황] 노트북에 델 외부 모니터를 꽂은 채로 진단한다.
# [기대] 부품의 화면 목록에는 노트북 내장 화면(Color LCD)만 남는다.
def test_외부_모니터는_부품에서_빼서_부품_변경으로_잘못_플래그되지_않는다():
    data = json.loads((FIXTURES / "displays.json").read_text(encoding="utf-8"))
    data["SPDisplaysDataType"][0]["spdisplays_ndrvs"].append(
        {"_name": "DELL U2720Q", "_spdisplays_pixels": "3840 x 2160", "spdisplays_connection_type": "spdisplays_dp"})
    displays = macos.parse_displays(json.dumps(data))
    assert [d["identifier"] for d in displays] == ["Color LCD"]


# [상황] 윈도우 노트북에 8GB 메모리 3개가 있고, 그중 하나는 일련번호가 00000000(의미 없는 값)이다.
# [기대] 합계 24GB, 모듈 3개, 의미 있는 일련번호만 모아 정렬해 남긴다(같은 용량 교체도 잡을 수 있게).
def test_윈도우_RAM은_모듈_시리얼을_모아_같은_용량_교체도_잡고_00000000은_뺀다():
    memory = json.dumps([{"Capacity": 8589934592, "SerialNumber": "B2C3", "PartNumber": "M425R1GB4BB0"},
                         {"Capacity": 8589934592, "SerialNumber": "A1B2", "PartNumber": "M425R1GB4BB0"},
                         {"Capacity": 8589934592, "SerialNumber": "00000000", "PartNumber": ""}])
    ram = windows.parse_memory(memory)[0]
    assert ram["identifier"] == "24 GB"
    assert ram["detail"] == {"totalBytes": 3 * 8589934592, "modules": 3, "serial": "A1B2,B2C3",
                             "partNumber": "M425R1GB4BB0"}


# [상황] 윈도우에서 배터리 정보 명령이 실패한다.
# [기대] 배터리 리포트(powercfg)에서 일련번호를 읽어 배터리 교체 여부를 잡을 수 있게 한다.
def test_BatteryStaticData가_실패하면_배터리_리포트의_시리얼로_배터리_교체를_잡는다():
    fail = Output(windows.BATTERY_STATIC, 1, "", "일반 오류")
    report_read = Output(windows.BATTERY_REPORT_READ, 0, json.dumps(
        {"DesignCapacity": "66990", "FullChargeCapacity": "47740", "CycleCount": "317", "SerialNumber": "SN-GB-01"}))
    collected = windows.collect(WinRunner({windows.BATTERY_STATIC: fail, windows.BATTERY_REPORT: Output(
        windows.BATTERY_REPORT, 0, ""), windows.BATTERY_REPORT_READ: report_read}))
    battery = next(c for c in collected["components"] if c["kind"] == "BATTERY")
    assert battery["detail"] == {"serial": "SN-GB-01"}


# [상황] C 드라이브 BitLocker가 켜져 있다. 다른 경우에는 관리자 권한이 없어 읽지 못한다.
# [기대] 켜져 있으면 경고 1개. 권한이 없으면 "모름"이고 요약에도 "BitLocker 모름"이 보인다.
def test_BitLocker가_켜져_있으면_경고하고_관리자_권한이_없으면_모름이다():
    on = Output(windows.BITLOCKER, 0, json.dumps([{"DriveLetter": "C:", "ProtectionStatus": 1},
                                                  {"DriveLetter": "D:", "ProtectionStatus": 0}]))
    checks = windows.collect(WinRunner({windows.BITLOCKER: on}))["checks"]
    assert checks["bitLocker"] == "켜짐" and len(checks["warnings"]) == 1
    denied = windows.collect(WinRunner())["checks"]  # 고정 파일 없음 = 권한 없음과 같다
    assert denied == {"bitLocker": None, "security": None, "threatCount": None, "warnings": []}
    assert "BitLocker 모름" in report.summary(_doc(windows.collect(WinRunner())), denied)


# [상황] 올리기 동의를 묻기 전 요약을 만든다.
# [기대] 올라갈 RAM·SSD 일련번호와 부품 번호가 요약에 그대로 보인다(고객이 무엇이 올라가는지 알고 동의).
def test_동의_전_요약에_올라가는_부품_시리얼과_부품_번호가_보인다():
    collected = windows.collect(WinRunner({windows.MEMORY: Output(windows.MEMORY, 0, json.dumps(
        [{"Capacity": 8589934592, "SerialNumber": "A1B2", "PartNumber": "M425R1GB4BB0"}]))}))
    text = report.summary(_doc(collected))
    assert "RAM serial A1B2 partNumber M425R1GB4BB0" in text and "SSD serial SSDTEST01" in text


# [상황] BitLocker 상태 값이 "알 수 없음(2)"이거나 비어 있다.
# [기대] "꺼짐"으로 단정하지 않고 "모름"으로 둔다. 0일 때만 "꺼짐".
def test_BitLocker_상태가_알_수_없음이나_빈_값이면_꺼짐이_아니라_모름이다():
    for status in (2, None):
        out = Output(windows.BITLOCKER, 0, json.dumps([{"DriveLetter": "C:", "ProtectionStatus": status}]))
        assert windows.collect(WinRunner({windows.BITLOCKER: out}))["checks"]["bitLocker"] is None
    off = Output(windows.BITLOCKER, 0, json.dumps([{"DriveLetter": "C:", "ProtectionStatus": 0}]))
    assert windows.collect(WinRunner({windows.BITLOCKER: off}))["checks"]["bitLocker"] == "꺼짐"
