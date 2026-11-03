"""고정 벤치마크 5종 × 3회와 중앙값(FR-DIA-04). 전원이 없으면 하나도 돌리지 않는다."""

from __future__ import annotations

import hashlib
import os
import statistics
import tempfile
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ProcessPoolExecutor
from typing import Any

TRIALS = 3
_MB = 1024 * 1024


def cpu_single(seconds: float = 1.5) -> float:
    """1 KB 블록 SHA-256 반복 횟수/초."""
    block, count, end = b"\0" * 1024, 0, time.perf_counter() + seconds
    while time.perf_counter() < end:
        for _ in range(200):
            hashlib.sha256(block).digest()
        count += 200
    return count / seconds


def cpu_multi(seconds: float = 1.5) -> float:
    workers = os.cpu_count() or 1
    with ProcessPoolExecutor(workers) as pool:
        return sum(pool.map(cpu_single, [seconds] * workers))


def mem_copy(size_mb: int = 64, rounds: int = 10) -> float:
    src = bytearray(size_mb * _MB)
    start = time.perf_counter()
    for _ in range(rounds):
        bytes(src)
    return size_mb * rounds / (time.perf_counter() - start)


def _no_cache(fd: int) -> None:
    """macOS F_NOCACHE: 디스크 값이 메모리 캐시 속도가 되지 않게."""
    try:
        import fcntl

        fcntl.fcntl(fd, 48, 1)
    except (ImportError, OSError):
        pass


def _drop_cache(fd: int) -> None:
    """리눅스: 쓴 뒤 페이지 캐시를 버려 읽기 값이 캐시 속도가 되지 않게. Windows는 AG2에서 따로 처리한다."""
    advise = getattr(os, "posix_fadvise", None)
    if advise is not None:
        try:
            advise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        except OSError:
            pass


def disk(size_mb: int = 256) -> tuple[float, float]:
    """임시 파일에 쓰고(fsync) 다시 읽은 MB/s. 파일은 바로 지운다. 사용자 파일은 건드리지 않는다."""
    chunk = os.urandom(_MB)
    fd, path = tempfile.mkstemp(prefix="trace-bench-")
    try:
        _no_cache(fd)
        start = time.perf_counter()
        for _ in range(size_mb):
            os.write(fd, chunk)
        os.fsync(fd)
        write = size_mb / (time.perf_counter() - start)
        _drop_cache(fd)
        os.lseek(fd, 0, os.SEEK_SET)
        start = time.perf_counter()
        while os.read(fd, 4 * _MB):
            pass
        read = size_mb / (time.perf_counter() - start)
    finally:
        os.close(fd)
        os.unlink(path)
    return read, write


def default_workloads(measure_disk: Callable[[], tuple[float, float]] = disk
                      ) -> dict[str, tuple[str, Callable[[], float]]]:
    """디스크는 회차마다 한 번만 쓰고 읽어 읽기·쓰기 값을 함께 쓴다(DISK_READ가 잰 쓰기 값을 DISK_WRITE가 꺼냄)."""
    writes: list[float] = []

    def disk_read() -> float:
        read, write = measure_disk()
        writes.append(write)
        return read

    def disk_write() -> float:
        return writes.pop(0) if writes else measure_disk()[1]

    return {
        "CPU_SINGLE": ("ops/s", cpu_single),
        "CPU_MULTI": ("ops/s", cpu_multi),
        "MEM_COPY": ("MB/s", mem_copy),
        "DISK_READ": ("MB/s", disk_read),
        "DISK_WRITE": ("MB/s", disk_write),
    }


def run(ac_power: bool, workloads: Mapping[str, tuple[str, Callable[[], float]]] | None = None,
        progress: Callable[[str], None] | None = None) -> tuple[list[dict[str, Any]], str | None]:
    """(benchmarks, benchmarkSkippedReason). 전원이 없으면 ([], "NO_AC_POWER"). progress는 지표마다 한 번 불린다."""
    if not ac_power:
        return [], "NO_AC_POWER"
    results = []
    jobs = workloads or default_workloads()
    for i, (metric, (unit, fn)) in enumerate(jobs.items(), 1):
        if progress:
            progress(f"벤치마크 {i}/{len(jobs)}: {metric} {TRIALS}회")
        trials = [round(fn(), 1) for _ in range(TRIALS)]
        results.append({"metric": metric, "unit": unit, "trials": trials, "median": statistics.median(trials)})
    return results, None
