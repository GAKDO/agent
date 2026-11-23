# 이 파일이 확인하는 것: 진단 에이전트 프로그램이 켜지고 버전을 제대로 알려 주는지(가장 기본 확인).

from trace_agent import __version__
from trace_agent.__main__ import main


# [상황] 에이전트 버전 값을 읽는다.
# [기대] 지금 배포 버전 0.3.0이다(설치 스크립트·웹 안내와 맞아야 함).
def test_version():
    assert __version__ == "0.3.0"


# [상황] 아무 옵션 없이 에이전트를 실행한다.
# [기대] 정상 종료(0)하고 화면에 버전 0.3.0을 보여 준다.
def test_main_prints_version(capsys):
    assert main([]) == 0
    assert "0.3.0" in capsys.readouterr().out
