"""이 파일이 확인하는 것: 노트북 성능 측정(벤치마크) 규칙.
지표 5개(CPU 단일·CPU 멀티·메모리 복사·디스크 읽기·디스크 쓰기)를 각각 3번 재고 가운데 값을 쓴다.
출고 때와 반납 때 값을 비교해 성능이 떨어졌는지 보기 위한 것이다. 충전기가 있을 때만 돌린다.

스토리 2: 전원이 있을 때만 벤치마크를 돌린다.
"""

from __future__ import annotations

from trace_agent import benchmark


# 도우미: 진짜로 계산하지 않고 3.0·1.0·2.0을 차례로 내는 가짜 측정 작업(몇 번 불렸는지 센다).
def counting_workloads(calls: list[str]) -> dict:
    values = iter([3.0, 1.0, 2.0] * 5)

    def make(metric: str):
        def fn() -> float:
            calls.append(metric)
            return next(values)
        return fn

    return {m: ("ops/s", make(m)) for m in ("CPU_SINGLE", "CPU_MULTI", "MEM_COPY", "DISK_READ", "DISK_WRITE")}


# [상황] 충전기가 연결되지 않았다.
# [기대] 측정을 하나도 하지 않고 사유 NO_AC_POWER만 남긴다.
def test_전원이_연결되지_않으면_벤치마크를_하나도_실행하지_않고_NO_AC_POWER를_남긴다():
    calls: list[str] = []
    assert benchmark.run(False, counting_workloads(calls)) == ([], "NO_AC_POWER")
    assert calls == []


# [상황] 충전기가 연결돼 있다.
# [기대] 지표 5개를 정해진 순서로 각각 3번(총 15번) 재고, 3번 값과 가운데 값(2.0)을 함께 남긴다.
def test_전원이_연결되면_지표_5개가_각각_3회와_그_가운데_값을_가진다():
    calls: list[str] = []
    results, reason = benchmark.run(True, counting_workloads(calls))

    assert reason is None and len(calls) == 15
    assert [r["metric"] for r in results] == ["CPU_SINGLE", "CPU_MULTI", "MEM_COPY", "DISK_READ", "DISK_WRITE"]
    assert all(r["trials"] == [3.0, 1.0, 2.0] and r["median"] == 2.0 for r in results)


# [상황] 진짜 측정 작업(CPU·메모리·디스크)을 아주 짧게 돌린다.
# [기대] 모두 0보다 큰 값을 내고, 디스크 측정에 쓴 임시 파일은 남기지 않는다(고객 컴퓨터를 어지르지 않음).
def test_실제_작업은_양수를_내고_디스크_임시_파일을_남기지_않는다(tmp_path, monkeypatch):
    monkeypatch.setattr(benchmark.tempfile, "tempdir", str(tmp_path))
    assert benchmark.cpu_single(0.02) > 0
    assert benchmark.mem_copy(1, 2) > 0
    read, write = benchmark.disk(2)
    assert read > 0 and write > 0
    assert list(tmp_path.iterdir()) == []


# [상황] 디스크 읽기·쓰기 지표를 잰다.
# [기대] 한 회차에 파일을 한 번만 쓰고 읽어 두 값을 함께 쓴다(3회차 = 디스크 작업 3번).
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


# [상황] 벤치마크를 돌리며 진행 알림을 받는다.
# [기대] 지표마다 "벤치마크 1/5: CPU_SINGLE 3회" 같은 안내가 5줄 나온다(고객이 멈춘 줄 알지 않게).
def test_벤치마크가_도는_동안_지표마다_진행을_알린다():
    lines: list[str] = []
    benchmark.run(True, counting_workloads([]), progress=lines.append)
    assert lines[0] == "벤치마크 1/5: CPU_SINGLE 3회" and len(lines) == 5
