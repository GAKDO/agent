# 이 파일이 확인하는 것: 맥 진단 수집(요구사항 스토리 1). 실제 맥북 에어 M2 출력 고정 파일로
# 배터리·SSD·기기 정보·부품·측정 조건을 제대로 읽는지 본다.

"""스토리 1 수용 시나리오: 실제 맥 출력(tests/fixtures/macos)으로 확인."""

from __future__ import annotations

import json

from conftest import FIXTURES, NOW, FixtureRunner

from trace_agent import macos
from trace_agent.commands import ALLOWED, Output

# SSD가 건강하다고 답하는 smartctl 출력(사용률 3%, 여유 공간 100%, 오류 0, 사용 812시간).
NVME_OK = json.dumps({"nvme_smart_health_information_log": {
    "critical_warning": 0, "available_spare": 100, "percentage_used": 3, "media_errors": 0, "power_on_hours": 812}})


# [상황] 실제 맥 출력에서 배터리 정보를 읽는다.
# [기대] 충전 횟수 186회·최대 용량 90%·상태 정상은 맥 "시스템 정보" 앱 값과 같고,
#        설계 용량 4563mAh·현재 완충 용량 4070mAh는 ioreg 값 그대로다.
def test_배터리_사이클과_최대_용량은_OS_값과_같고_용량은_ioreg_mAh_그대로다(runner):
    battery = macos.collect(runner, now=NOW)["battery"]

    assert battery["status"] == "OK"
    assert battery["cycleCount"] == 186  # 시스템 정보 앱 전원 항목의 충전 횟수
    assert battery["osMaxCapacityPercent"] == 90  # "90%"
    assert battery["osCondition"] == "NORMAL"  # "Good"
    assert battery["designCapacity"] == {"value": 4563, "unit": "mAh"}
    assert battery["fullChargeCapacity"] == {"value": 4070, "unit": "mAh"}  # NominalChargeCapacity


# [상황] 맥이 충전 횟수를 0으로 알려 준다(새 배터리가 아니라 값을 못 읽은 경우가 많음).
# [기대] 0을 믿지 않고 "모름(null)"으로 둔다.
def test_OS가_사이클을_0으로_주면_cycleCount는_null이다():
    text = (FIXTURES / "power.json").read_text().replace('"sppower_battery_cycle_count" : 186', '"sppower_battery_cycle_count" : 0')
    runner = FixtureRunner({macos.POWER: Output(macos.POWER, 0, text)})
    assert macos.collect(runner, now=NOW)["battery"]["cycleCount"] is None


# [상황] SSD 건강 도구(smartctl)가 설치돼 있지 않거나, 권한이 없어 실패한다.
# [기대] SSD 항목은 "건너뜀"과 사유(도구 오류 / 권한 없음)를 남기고 값은 모두 비운다(추측하지 않음).
def test_smartctl이_없거나_실패하면_SSD는_SKIPPED와_사유가_남고_값은_모두_null이다(runner):
    storage = macos.collect(runner, now=NOW)["storage"]
    assert storage["status"] == "SKIPPED" and storage["skippedReason"] == "TOOL_ERROR"
    assert all(storage[k] is None for k in ("protocol", "percentageUsed", "availableSpare", "criticalWarning",
                                             "mediaErrors", "powerOnHours"))

    denied = Output(macos.SMARTCTL, 2, json.dumps({"smartctl": {"messages": [
        {"string": "Smartctl open device: /dev/disk0 failed: Operation not permitted"}]}}))
    assert macos.parse_smartctl(denied)["skippedReason"] == "NO_PERMISSION"


# [상황] smartctl이 SSD 건강 정보를 정상으로 준다.
# [기대] 사용률·여유 공간·경고·오류 수·사용 시간을 각각 따로 남긴다.
def test_smartctl이_NVMe_건강_로그를_주면_값을_따로_남긴다():
    storage = macos.parse_smartctl(Output(macos.SMARTCTL, 0, NVME_OK))
    assert storage == {"status": "OK", "skippedReason": None, "protocol": "NVME", "percentageUsed": 3,
                       "availableSpare": 100, "criticalWarning": 0, "mediaErrors": 0, "powerOnHours": 812}


# [상황] 배터리가 없는 맥(데스크톱)에서 진단한다.
# [기대] 배터리 상태 NO_BATTERY, 값은 모두 비우고, 부품 목록에도 배터리를 넣지 않는다.
def test_배터리가_없는_맥은_NO_BATTERY이고_값은_모두_null이다():
    runner = FixtureRunner({
        macos.POWER: Output(macos.POWER, 0, json.dumps({"SPPowerDataType": [{"_name": "sppower_information"}]})),
        macos.IOREG_BATTERY: Output(macos.IOREG_BATTERY, 0, ""),
    })
    collected = macos.collect(runner, now=NOW)
    assert collected["battery"]["status"] == "NO_BATTERY"
    assert all(v is None for k, v in collected["battery"].items() if k != "status")
    assert "BATTERY" not in [c["kind"] for c in collected["components"]]


# [상황] 실제 맥 출력에서 기기·부품·측정 조건을 읽는다.
# [기대] 기기(일련번호·제조사·모델), 부품(CPU 코어 수·RAM 16GB·SSD·배터리·화면 해상도),
#        측정 조건(충전기 없음·배터리 59%·발열 정상·프로세스 745개·가동 5400초)이 정확히 나온다.
#        부품 일련번호는 나중에 출고 때와 비교해 "부품이 바뀌었는지" 찾는 데 쓴다.
def test_기기와_부품과_측정_조건을_읽는다(runner):
    collected = macos.collect(runner, now=NOW)

    assert collected["device"] == {"serial": "C02TEST00001", "manufacturer": "Apple", "model": "Mac14,2",
                                   "modelName": "MacBook Air"}
    kinds = {c["kind"]: c for c in collected["components"]}
    assert kinds["CPU"] == {"kind": "CPU", "identifier": "Apple M2",
                            "detail": {"cores": 8, "performanceCores": 4, "efficiencyCores": 4}}
    assert kinds["RAM"]["detail"]["totalBytes"] == 16 * 1024**3
    assert kinds["SSD"]["detail"] == {"serial": "SSDTEST01", "capacityBytes": 251000193024, "smartStatus": "Verified"}
    assert kinds["BATTERY"] == {"kind": "BATTERY", "identifier": "bq40z651", "detail": {"serial": "BATTEST01"}}
    assert kinds["DISPLAY"]["detail"] == {"resolution": "3420x2224"}
    assert collected["conditions"] == {"acPower": False, "batteryPercent": 59, "thermalState": "NOMINAL",
                                       "processCount": 745, "uptimeSec": 5400}


# [상황] 진단을 한 번 돌리고 실행된 명령을 모은다.
# [기대] 모두 허용 목록 안이고, 진단 문서의 출처(sources)에 실행 순서대로 남는다.
def test_실행한_명령은_모두_고정_목록_안에_있고_sources에_남는다(runner):
    collected = macos.collect(runner, now=NOW)
    assert set(runner.calls) <= set(ALLOWED)
    assert collected["sources"] == [" ".join(argv) for argv in runner.calls]
