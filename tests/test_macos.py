"""스토리 1 수용 시나리오: 실제 맥 출력(tests/fixtures/macos)으로 확인."""

from __future__ import annotations

import json

from conftest import FIXTURES, NOW, FixtureRunner

from trace_agent import macos
from trace_agent.commands import ALLOWED, Output

NVME_OK = json.dumps({"nvme_smart_health_information_log": {
    "critical_warning": 0, "available_spare": 100, "percentage_used": 3, "media_errors": 0, "power_on_hours": 812}})


def test_배터리_사이클과_최대_용량은_OS_값과_같고_용량은_ioreg_mAh_그대로다(runner):
    battery = macos.collect(runner, now=NOW)["battery"]

    assert battery["status"] == "OK"
    assert battery["cycleCount"] == 186  # 시스템 정보 앱 전원 항목의 충전 횟수
    assert battery["osMaxCapacityPercent"] == 90  # "90%"
    assert battery["osCondition"] == "NORMAL"  # "Good"
    assert battery["designCapacity"] == {"value": 4563, "unit": "mAh"}
    assert battery["fullChargeCapacity"] == {"value": 4070, "unit": "mAh"}  # NominalChargeCapacity


def test_OS가_사이클을_0으로_주면_cycleCount는_null이다():
    text = (FIXTURES / "power.json").read_text().replace('"sppower_battery_cycle_count" : 186', '"sppower_battery_cycle_count" : 0')
    runner = FixtureRunner({macos.POWER: Output(macos.POWER, 0, text)})
    assert macos.collect(runner, now=NOW)["battery"]["cycleCount"] is None


def test_smartctl이_없거나_실패하면_SSD는_SKIPPED와_사유가_남고_값은_모두_null이다(runner):
    storage = macos.collect(runner, now=NOW)["storage"]
    assert storage["status"] == "SKIPPED" and storage["skippedReason"] == "TOOL_ERROR"
    assert all(storage[k] is None for k in ("protocol", "percentageUsed", "availableSpare", "criticalWarning",
                                             "mediaErrors", "powerOnHours"))

    denied = Output(macos.SMARTCTL, 2, json.dumps({"smartctl": {"messages": [
        {"string": "Smartctl open device: /dev/disk0 failed: Operation not permitted"}]}}))
    assert macos.parse_smartctl(denied)["skippedReason"] == "NO_PERMISSION"


def test_smartctl이_NVMe_건강_로그를_주면_값을_따로_남긴다():
    storage = macos.parse_smartctl(Output(macos.SMARTCTL, 0, NVME_OK))
    assert storage == {"status": "OK", "skippedReason": None, "protocol": "NVME", "percentageUsed": 3,
                       "availableSpare": 100, "criticalWarning": 0, "mediaErrors": 0, "powerOnHours": 812}


def test_배터리가_없는_맥은_NO_BATTERY이고_값은_모두_null이다():
    runner = FixtureRunner({
        macos.POWER: Output(macos.POWER, 0, json.dumps({"SPPowerDataType": [{"_name": "sppower_information"}]})),
        macos.IOREG_BATTERY: Output(macos.IOREG_BATTERY, 0, ""),
    })
    collected = macos.collect(runner, now=NOW)
    assert collected["battery"]["status"] == "NO_BATTERY"
    assert all(v is None for k, v in collected["battery"].items() if k != "status")
    assert "BATTERY" not in [c["kind"] for c in collected["components"]]


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


def test_실행한_명령은_모두_고정_목록_안에_있고_sources에_남는다(runner):
    collected = macos.collect(runner, now=NOW)
    assert set(runner.calls) <= set(ALLOWED)
    assert collected["sources"] == [" ".join(argv) for argv in runner.calls]
