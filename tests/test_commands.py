# 이 파일이 확인하는 것: 에이전트가 고객 노트북에서 실행할 수 있는 명령을 미리 정한 목록으로만 제한하는지.
# 고객 컴퓨터의 개인 파일·브라우저 기록 같은 것은 절대 읽지 않는다는 약속을 코드로 지킨다.

import pytest

from trace_agent.commands import ALLOWED, NotAllowed, run


# [상황] 목록에 없는 명령(비밀번호 파일 읽기, 설치된 앱 목록 읽기)을 실행하려 한다.
# [기대] 실행하지 않고 "허용 안 됨" 오류를 낸다.
def test_고정_목록_밖의_명령은_실행하지_않는다():
    with pytest.raises(NotAllowed):
        run(("cat", "/etc/passwd"))
    with pytest.raises(NotAllowed):
        run(("system_profiler", "SPApplicationsDataType", "-json"))


# [상황] 허용된 명령 전체를 글자로 펼쳐 본다.
# [기대] 사용자 폴더·Library·사파리·크롬·방문 기록·쿠키·키체인 같은 단어가 하나도 없다.
def test_읽는_명령_목록에_사용자_폴더나_브라우저_기록_경로가_없다():
    joined = " ".join(" ".join(argv) for argv in ALLOWED).lower()
    for word in ("~", "/users", "library", "safari", "chrome", "history", "cookies", "keychain"):
        assert word not in joined


# [상황] 회사 보안 프로그램 등이 명령 실행 자체를 막는다.
# [기대] 프로그램이 멈추지 않고 그 항목을 "읽지 못함(실행 실패)"으로 두고 계속 진행한다.
def test_실행이_막히면_읽지_못함으로_두고_계속한다(monkeypatch):
    import subprocess

    def deny(*_a, **_k):
        raise PermissionError("blocked")

    monkeypatch.setattr(subprocess, "run", deny)
    out = run(next(iter(ALLOWED)))
    assert out.code is None and "실행 실패" in out.stderr
