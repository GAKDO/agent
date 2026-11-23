# 이 파일이 확인하는 것: 충전기 확인 안내(11/9 추가).
# 노트북 성능 측정(벤치마크)은 배터리로 돌면 값이 낮게 나오므로 충전기가 연결됐을 때만 돌린다.
# 충전기가 없으면 "충전기를 꽂고 Enter를 누르세요"라고 묻고, 꽂으면 다시 확인해 벤치마크를 돌린다.

"""충전기 확인(11/9): 전원이 없으면 벤치마크 전에 묻고, 꽂으면 다시 확인해 벤치마크를 돌린다."""

from __future__ import annotations

import json

from conftest import FixtureRunner
from test_upload import AC, ENV, clock, fast_workloads

from trace_agent import macos
from trace_agent.__main__ import main


# 가짜 실행기: 처음 전원 확인은 "배터리 사용 중", 그다음부터는 "충전기 연결됨"으로 답한다(중간에 꽂은 상황).
class PlugInRunner(FixtureRunner):
    """처음 pmset은 배터리(고정 파일), 그다음부터는 충전기를 꽂은 출력."""

    def __call__(self, argv):
        if argv == macos.PMSET_BATT and argv in self.calls:
            self.calls.append(argv)
            return AC
        return super().__call__(argv)


# 도우미: 고객 대답(Enter·n 등)을 차례로 넣으며 에이전트를 끝까지 돌리고, 만든 진단 문서와 받은 질문을 돌려준다.
def _run(tmp_path, answers: list[str], runner) -> tuple[dict, list[str]]:
    asked: list[str] = []
    feed = iter(answers)

    def ask(question: str) -> str:
        asked.append(question)
        return next(feed)

    out = tmp_path / "diag.json"
    assert main(["run", "--out", str(out)], env=ENV, ask=ask, run=runner, post=lambda *_: (500, {}),
                workloads=fast_workloads(), clock=clock(), system="darwin") == 0
    return json.loads(out.read_text(encoding="utf-8")), asked


# [상황] 충전기 없이 시작 → 질문을 받고 충전기를 꽂은 뒤 Enter를 누른다.
# [기대] 한 번만 묻고, 다시 확인해 "충전기가 연결됐어요"를 보여 준 뒤 벤치마크를 돌린다.
def test_충전기를_꽂고_Enter를_누르면_다시_확인해_벤치마크를_돌린다(tmp_path, capsys) -> None:
    doc, asked = _run(tmp_path, [""], PlugInRunner())
    assert len(asked) == 1 and "충전기" in asked[0]
    assert doc["conditions"]["acPower"] is True
    assert doc["benchmarks"] and doc["benchmarkSkippedReason"] is None
    assert "충전기가 연결됐어요" in capsys.readouterr().out


# [상황] 충전기 질문에 n(아니오)을 넣는다.
# [기대] 벤치마크 없이 진행하고 사유를 NO_AC_POWER(전원 없음)로 남긴다.
def test_n을_넣으면_충전기_없이_벤치마크를_건너뛴다(tmp_path) -> None:
    doc, asked = _run(tmp_path, ["n"], FixtureRunner())
    assert len(asked) == 1
    assert doc["conditions"]["acPower"] is False
    assert doc["benchmarks"] == [] and doc["benchmarkSkippedReason"] == "NO_AC_POWER"


# [상황] Enter를 세 번 눌렀는데도 충전기가 계속 없다.
# [기대] 세 번 물은 뒤 포기하고 벤치마크 없이 진행한다(무한히 묻지 않음).
def test_세_번_확인해도_충전기가_없으면_건너뛰고_진행한다(tmp_path) -> None:
    doc, asked = _run(tmp_path, ["", "", ""], FixtureRunner())
    assert len(asked) == 3
    assert doc["benchmarkSkippedReason"] == "NO_AC_POWER"


# [상황] 처음부터 충전기가 꽂혀 있다.
# [기대] 아무것도 묻지 않고 바로 벤치마크를 돌린다.
def test_전원이_이미_연결돼_있으면_묻지_않는다(tmp_path) -> None:
    doc, asked = _run(tmp_path, [], FixtureRunner({macos.PMSET_BATT: AC}))
    assert asked == [] and doc["benchmarks"]
