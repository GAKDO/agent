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
