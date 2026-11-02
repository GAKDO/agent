"""실행할 수 있는 명령의 고정 목록(NFR-02)과 실행 함수.

목록 밖 명령은 실행하지 않는다. 사용자 폴더·브라우저 기록을 읽는 명령은 목록에 없다.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass

ALLOWED: tuple[tuple[str, ...], ...] = (
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
        done = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, check=False)
    except FileNotFoundError:
        return Output(argv, None, "", "명령 없음")
    except subprocess.TimeoutExpired:
        return Output(argv, None, "", "시간 초과")
    return Output(argv, done.returncode, done.stdout, done.stderr)
