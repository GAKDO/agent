import pytest

from trace_agent.commands import ALLOWED, NotAllowed, run


def test_고정_목록_밖의_명령은_실행하지_않는다():
    with pytest.raises(NotAllowed):
        run(("cat", "/etc/passwd"))
    with pytest.raises(NotAllowed):
        run(("system_profiler", "SPApplicationsDataType", "-json"))


def test_읽는_명령_목록에_사용자_폴더나_브라우저_기록_경로가_없다():
    joined = " ".join(" ".join(argv) for argv in ALLOWED).lower()
    for word in ("~", "/users", "library", "safari", "chrome", "history", "cookies", "keychain"):
        assert word not in joined


def test_실행이_막히면_읽지_못함으로_두고_계속한다(monkeypatch):
    import subprocess

    def deny(*_a, **_k):
        raise PermissionError("blocked")

    monkeypatch.setattr(subprocess, "run", deny)
    out = run(next(iter(ALLOWED)))
    assert out.code is None and "실행 실패" in out.stderr
