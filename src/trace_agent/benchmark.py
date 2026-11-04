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
    """미리 잡은 버퍼에 복사한 MB/s. 회차마다 새로 할당하면 OS의 페이지 할당 비용(특히 Windows)이 섞인다."""
    src, dst = bytearray(size_mb * _MB), bytearray(size_mb * _MB)
    dst[:] = src  # 페이지를 먼저 잡아 둔다
    start = time.perf_counter()
    for _ in range(rounds):
        dst[:] = src
    return size_mb * rounds / (time.perf_counter() - start)


def _no_cache(fd: int) -> None:
    """macOS F_NOCACHE: 디스크 값이 메모리 캐시 속도가 되지 않게."""
    try:
        import fcntl

        fcntl.fcntl(fd, 48, 1)
    except (ImportError, OSError):
        pass


def _full_sync(fd: int) -> None:
    """macOS F_FULLFSYNC: fsync만으로는 SSD 안 캐시에 남아 쓰기 값이 들쭉날쭉하다. 없는 OS는 fsync."""
    try:
        import fcntl

        fcntl.fcntl(fd, getattr(fcntl, "F_FULLFSYNC", 51))
        return
    except (ImportError, OSError):
        pass
    os.fsync(fd)


def _drop_cache(fd: int) -> None:
    """리눅스: 쓴 뒤 페이지 캐시를 버려 읽기 값이 캐시 속도가 되지 않게."""
    advise = getattr(os, "posix_fadvise", None)
    if advise is not None:
        try:
            advise(fd, 0, 0, os.POSIX_FADV_DONTNEED)
        except OSError:
            pass


def _posix_io(path: str, size_mb: int) -> tuple[float, float]:
    """캐시를 끈 핸들로 쓰고(F_FULLFSYNC) 닫은 뒤, 캐시를 끈 새 핸들로 읽는다(맥에서 3회 편차 ±1% 안팎)."""
    chunk_mb = 4 if size_mb % 4 == 0 else 1
    chunk = os.urandom(chunk_mb * _MB)
    fd = os.open(path, os.O_WRONLY | getattr(os, "O_BINARY", 0))
    try:
        _no_cache(fd)
        start = time.perf_counter()
        for _ in range(size_mb // chunk_mb):
            os.write(fd, chunk)
        _full_sync(fd)
        write = size_mb / (time.perf_counter() - start)
    finally:
        os.close(fd)
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0))
    try:
        _no_cache(fd)
        _drop_cache(fd)
        start = time.perf_counter()
        while os.read(fd, 4 * _MB):
            pass
        read = size_mb / (time.perf_counter() - start)
    finally:
        os.close(fd)
    return read, write


def _windows_io(path: str, size_mb: int) -> tuple[float, float] | None:
    """Windows: FILE_FLAG_NO_BUFFERING(+쓰기는 WRITE_THROUGH)로 캐시를 거치지 않고 쓰고 읽은 MB/s. 실패하면 None."""
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return None
    k = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    k.CreateFileW.restype = wintypes.HANDLE
    k.VirtualAlloc.restype = ctypes.c_void_p
    k.VirtualAlloc.argtypes = (ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD)
    k.VirtualFree.argtypes = (ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD)
    io_args = (wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p)
    k.ReadFile.argtypes = k.WriteFile.argtypes = io_args
    k.FlushFileBuffers.argtypes = k.CloseHandle.argtypes = (wintypes.HANDLE,)
    invalid = wintypes.HANDLE(-1).value
    generic_read, generic_write, share_all, open_existing = 0x80000000, 0x40000000, 0x7, 3
    no_buffering, write_through, sequential = 0x20000000, 0x80000000, 0x08000000
    size = _MB  # 섹터 크기의 배수이고, VirtualAlloc 버퍼는 페이지 정렬이라 NO_BUFFERING 조건을 맞춘다
    buf = k.VirtualAlloc(None, size, 0x3000, 0x04)  # MEM_COMMIT|MEM_RESERVE, PAGE_READWRITE
    if not buf:
        return None
    try:
        ctypes.memmove(buf, os.urandom(size), size)
        done = wintypes.DWORD(0)
        handle = k.CreateFileW(path, generic_write, share_all, None, open_existing, no_buffering | write_through, None)
        if handle in (None, invalid):
            return None
        try:
            start = time.perf_counter()
            for _ in range(size_mb):
                if not k.WriteFile(handle, buf, size, ctypes.byref(done), None) or done.value != size:
                    return None
            k.FlushFileBuffers(handle)
            write = size_mb / (time.perf_counter() - start)
        finally:
            k.CloseHandle(handle)
        handle = k.CreateFileW(path, generic_read, share_all, None, open_existing, no_buffering | sequential, None)
        if handle in (None, invalid):
            return None
        try:
            total, start = 0, time.perf_counter()
            while k.ReadFile(handle, buf, size, ctypes.byref(done), None) and done.value:
                total += done.value
            elapsed = time.perf_counter() - start
        finally:
            k.CloseHandle(handle)
        return (total / _MB / elapsed, write) if total and elapsed > 0 else None
    finally:
        k.VirtualFree(buf, 0, 0x8000)  # MEM_RELEASE


def disk(size_mb: int = 256) -> tuple[float, float]:
    """임시 파일에 쓰고 다시 읽은 (읽기, 쓰기) MB/s. 둘 다 OS 캐시를 거치지 않게 잰다. 파일은 바로 지운다.
    사용자 파일은 건드리지 않는다."""
    fd, path = tempfile.mkstemp(prefix="trace-bench-")
    os.close(fd)
    try:
        if os.name == "nt" and (measured := _windows_io(path, size_mb)) is not None:
            return measured
        return _posix_io(path, size_mb)
    finally:
        os.unlink(path)


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
