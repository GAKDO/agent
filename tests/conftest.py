"""테스트 공통 준비물(테스트 자체는 아님): 진단 에이전트가 맥에서 실행하는 명령(system_profiler·ioreg·pmset 등)의
출력을 진짜로 실행하지 않고, 실제 맥북 에어(M2)에서 미리 받아 둔 출력 파일(tests/fixtures/macos)로 돌려준다.
그래서 어떤 컴퓨터(리눅스 CI 포함)에서도 "그 맥북에서 진단을 돌린 것처럼" 시험할 수 있다.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trace_agent import macos
from trace_agent.commands import Output

FIXTURES = Path(__file__).parent / "fixtures" / "macos"
# 에이전트가 읽는 맥 명령 → 그 명령의 실제 출력을 저장해 둔 파일 이름.
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
    macos.GATEKEEPER: "spctl.txt",
    macos.SIP: "csrutil.txt",
}
# 실행 중인 프로세스 745개짜리 가짜 출력(측정 조건 "프로세스 수" 확인용).
PS_745 = "\n".join(str(i) for i in range(1, 746)) + "\n"
# "지금"을 부팅 1시간 30분 뒤로 고정한다(가동 시간 계산 확인용).
NOW = 1792657819 + 5400  # 부팅 1시간 30분 뒤


# 가짜 명령 실행기. 고정 파일 대신 다른 출력을 주고 싶으면 overrides로 바꿔 끼운다.
# smartctl(SSD 건강 정보 도구)은 이 맥에 설치돼 있지 않았던 상황을 그대로 흉내 낸다.
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
    """맥 진단 명령(system_profiler·ioreg·pmset 등)에 실제 맥북 에어(M2)에서 받아 둔 출력을 돌려주는 가짜 실행기."""
    return FixtureRunner()
