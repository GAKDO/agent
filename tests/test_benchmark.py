"""스토리 2: 전원이 있을 때만 벤치마크를 돌린다."""

from __future__ import annotations

from trace_agent import benchmark


def counting_workloads(calls: list[str]) -> dict:
    values = iter([3.0, 1.0, 2.0] * 5)

    def make(metric: str):
        def fn() -> float:
            calls.append(metric)
            return next(values)
        return fn

    return {m: ("ops/s", make(m)) for m in ("CPU_SINGLE", "CPU_MULTI", "MEM_COPY", "DISK_READ", "DISK_WRITE")}


def test_전원이_연결되지_않으면_벤치마크를_하나도_실행하지_않고_NO_AC_POWER를_남긴다():
    calls: list[str] = []
    assert benchmark.run(False, counting_workloads(calls)) == ([], "NO_AC_POWER")
    assert calls == []


def test_전원이_연결되면_지표_5개가_각각_3회와_그_가운데_값을_가진다():
    calls: list[str] = []
    results, reason = benchmark.run(True, counting_workloads(calls))

    assert reason is None and len(calls) == 15
    assert [r["metric"] for r in results] == ["CPU_SINGLE", "CPU_MULTI", "MEM_COPY", "DISK_READ", "DISK_WRITE"]
    assert all(r["trials"] == [3.0, 1.0, 2.0] and r["median"] == 2.0 for r in results)


def test_실제_작업은_양수를_내고_디스크_임시_파일을_남기지_않는다(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark.tempfile, "tempdir", str(tmp_path))
    assert benchmark.cpu_single(0.02) > 0
    assert benchmark.mem_copy(1, 2) > 0
    read, write = benchmark.disk(2)
    assert read > 0 and write > 0
    assert list(tmp_path.iterdir()) == []
