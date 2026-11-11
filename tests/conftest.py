from __future__ import annotations

from pathlib import Path

import pytest

from trace_agent import macos
from trace_agent.commands import Output

FIXTURES = Path(__file__).parent / "fixtures" / "macos"
FILES = {
    macos.HARDWARE: "hardware.json",
    macos.POWER: "power.json",
    macos.NVME: "nvme.json",
    macos.DISPLAYS: "displays.json",
    macos.IOREG_BATTERY: "ioreg_battery.plist",
    macos.PMSET_BATT: "pmset_batt.txt",
    macos.PMSET_THERM: "pmset_therm.txt",
    macos.BOOTTIME: "boottime.txt",
    macos.FILEVAULT: "fdesetup.txt",
}
PS_745 = "\n".join(str(i) for i in range(1, 746)) + "\n"
NOW = 1792657819 + 5400  # 부팅 1시간 30분 뒤


class FixtureRunner:
    """실제 맥 출력 고정 파일을 돌려주는 가짜 실행기. 바꿔 끼울 출력은 overrides로."""

    def __init__(self, overrides: dict[tuple[str, ...], Output] | None = None) -> None:
        self.overrides = overrides or {}
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: tuple[str, ...]) -> Output:
        self.calls.append(argv)
        if argv in self.overrides:
            return self.overrides[argv]
        if argv == macos.PS:
            return Output(argv, 0, PS_745)
        if argv == macos.SMARTCTL:
            return Output(argv, None, "", "명령 없음")  # 이 맥에는 smartctl이 없었다
        return Output(argv, 0, (FIXTURES / FILES[argv]).read_text(encoding="utf-8"))


@pytest.fixture
def runner() -> FixtureRunner:
    return FixtureRunner()
