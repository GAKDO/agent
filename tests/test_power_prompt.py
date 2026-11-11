"""충전기 확인(11/9): 전원이 없으면 벤치마크 전에 묻고, 꽂으면 다시 확인해 벤치마크를 돌린다."""

from __future__ import annotations

import json

from conftest import FixtureRunner
from test_upload import AC, ENV, clock, fast_workloads

from trace_agent import macos
from trace_agent.__main__ import main


class PlugInRunner(FixtureRunner):
    """처음 pmset은 배터리(고정 파일), 그다음부터는 충전기를 꽂은 출력."""

    def __call__(self, argv):
        if argv == macos.PMSET_BATT and argv in self.calls:
            self.calls.append(argv)
            return AC
        return super().__call__(argv)


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


def test_충전기를_꽂고_Enter를_누르면_다시_확인해_벤치마크를_돌린다(tmp_path, capsys) -> None:
    doc, asked = _run(tmp_path, [""], PlugInRunner())
    assert len(asked) == 1 and "충전기" in asked[0]
    assert doc["conditions"]["acPower"] is True
    assert doc["benchmarks"] and doc["benchmarkSkippedReason"] is None
    assert "충전기가 연결됐어요" in capsys.readouterr().out


def test_n을_넣으면_충전기_없이_벤치마크를_건너뛴다(tmp_path) -> None:
    doc, asked = _run(tmp_path, ["n"], FixtureRunner())
    assert len(asked) == 1
    assert doc["conditions"]["acPower"] is False
    assert doc["benchmarks"] == [] and doc["benchmarkSkippedReason"] == "NO_AC_POWER"


def test_세_번_확인해도_충전기가_없으면_건너뛰고_진행한다(tmp_path) -> None:
    doc, asked = _run(tmp_path, ["", "", ""], FixtureRunner())
    assert len(asked) == 3
    assert doc["benchmarkSkippedReason"] == "NO_AC_POWER"


def test_전원이_이미_연결돼_있으면_묻지_않는다(tmp_path) -> None:
    doc, asked = _run(tmp_path, [], FixtureRunner({macos.PMSET_BATT: AC}))
    assert asked == [] and doc["benchmarks"]
