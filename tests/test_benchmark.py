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


def test_디스크는_회차마다_한_번만_쓰고_읽어_읽기와_쓰기_값을_함께_쓴다():
    calls: list[int] = []

    def fake_disk() -> tuple[float, float]:
        calls.append(1)
        return 100.0 + len(calls), 10.0 + len(calls)

    workloads = benchmark.default_workloads(fake_disk)
    jobs = {m: workloads[m] for m in ("DISK_READ", "DISK_WRITE")}
    results, _ = benchmark.run(True, jobs)

    assert len(calls) == 3
    assert results[0]["trials"] == [101.0, 102.0, 103.0]
    assert results[1]["trials"] == [11.0, 12.0, 13.0]


def test_벤치마크가_도는_동안_지표마다_진행을_알린다():
    lines: list[str] = []
    benchmark.run(True, counting_workloads([]), progress=lines.append)
    assert lines[0] == "벤치마크 1/5: CPU_SINGLE 3회" and len(lines) == 5
