# 이 파일이 확인하는 것: 한 줄 설치 스크립트(install/agent.sh, "curl ... | sh" 로 설치).
# 고객이 웹에서 받은 명령 한 줄로 에이전트를 내려받고 파이썬 준비부터 진단 실행까지 되는지 본다.
# 리눅스·맥에서만 돌고, 실제 설치·다운로드가 일어나는 테스트는 리눅스 CI에서만 돈다.

"""한 줄 설치 스크립트(install/agent.sh): 코드 검사와, 받은 소스로 에이전트를 실제로 부르는지."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "install" / "agent.sh"

pytestmark = pytest.mark.skipif(sys.platform == "win32" or shutil.which("sh") is None, reason="POSIX sh 필요")


# 도우미: 설치 스크립트를 "curl | sh -s"처럼 표준 입력으로 넣어 실행한다.
def _sh(args: list[str], env: dict[str, str], script: str | None = None) -> subprocess.CompletedProcess[str]:
    # curl | sh -s 처럼 스크립트를 표준 입력으로 준다
    text = SCRIPT.read_text(encoding="utf-8") if script is None else script
    return subprocess.run(["sh", "-s", *args], check=False, input=text,
                          capture_output=True,
                          text=True, env=env, timeout=300)


# [상황] 페어링 코드로 6자리 숫자가 아닌 "12ab"를 넣는다.
# [기대] 아무것도 내려받기 전에 "6자리" 안내와 함께 멈추고, 설치 폴더도 만들지 않는다.
def test_6자리가_아닌_코드는_받기_전에_멈춘다(tmp_path: Path) -> None:
    result = _sh(["12ab"], {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert result.returncode == 1
    assert "6자리" in result.stderr
    assert not (tmp_path / ".trace-agent").exists()


# 도우미: 이 레포 소스를 GitHub에서 받는 압축 파일 모양으로 묶는다(인터넷 대신 사용).
def _archive(tmp_path: Path) -> Path:
    archive = tmp_path / "agent.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(ROOT / "src", arcname="agent-develop/src")
        tar.add(ROOT / "pyproject.toml", arcname="agent-develop/pyproject.toml")
    return archive


# [상황] 설치 스크립트가 소스 압축 파일을 받아 풀고 에이전트를 실행한다.
# [기대] 설치 폴더에 소스가 풀리고 "기기 정보를 읽는 중"이 나오며 진단 결과 파일이 생긴다.
@pytest.mark.skipif(sys.platform != "linux", reason="macOS CI에서는 실제 수집·벤치마크가 돌아 오래 걸린다")
def test_받은_소스를_풀어_에이전트를_부른다(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(tmp_path),
           "TRACE_AGENT_HOME": str(home), "TRACE_AGENT_SRC": _archive(tmp_path).as_uri()}
    result = _sh([], env)
    assert (home / "src" / "trace_agent" / "__main__.py").exists()
    assert "기기 정보를 읽는 중" in result.stdout
    assert (home / "trace-diagnostics.json").exists()


# [상황] 아무 패키지도 없는 새 파이썬(시연 노트북처럼)에서 설치한다.
# [기대] 필요한 검사 도구(jsonschema)를 설치 폴더 lib에 받아 쓰고, 모듈 없음 오류 없이 진단을 마친다.
@pytest.mark.skipif(sys.platform != "linux", reason="macOS CI에서는 실제 수집·벤치마크가 돌아 오래 걸린다")
def test_jsonschema가_없는_새_파이썬이면_lib에_받아_쓴다(tmp_path: Path) -> None:
    venv = tmp_path / "venv"  # 패키지가 하나도 없는 새 파이썬(시연 노트북처럼)
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    home = tmp_path / "home"
    env = {"PATH": f"{venv / 'bin'}:/usr/bin:/bin", "HOME": str(tmp_path), "TRACE_AGENT_HOME": str(home),
           "TRACE_AGENT_SRC": _archive(tmp_path).as_uri()}
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "NO_PROXY", "PIP_CERT", "SSL_CERT_FILE",
                "REQUESTS_CA_BUNDLE", "PIP_INDEX_URL"):
        if key in os.environ:
            env[key] = os.environ[key]
    result = _sh([], env)
    assert (home / "lib" / "jsonschema").is_dir(), result.stdout + result.stderr
    assert "기기 정보를 읽는 중" in result.stdout
    assert "ModuleNotFoundError" not in result.stderr
    assert (home / "trace-diagnostics.json").exists()


# 도우미: 이 테스트 환경의 인터넷 프록시 설정을 설치 스크립트에도 넘긴다.
def _net_env(env: dict[str, str]) -> dict[str, str]:
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "NO_PROXY", "no_proxy", "PIP_CERT",
                "SSL_CERT_FILE", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "PIP_INDEX_URL"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


# [상황] 컴퓨터에 쓸 만한 파이썬(3.11 이상)이 없다(친구 맥에서 실제로 있었던 경우).
# [기대] 독립 실행형 파이썬을 설치 폴더에 받아 그것으로 진단을 돌린다.
@pytest.mark.skipif(sys.platform != "linux", reason="macOS CI에서는 실제 수집·벤치마크가 돌아 오래 걸린다")
def test_파이썬이_없으면_독립_실행형_파이썬을_받아_쓴다(tmp_path: Path) -> None:
    script = SCRIPT.read_text(encoding="utf-8")
    line = next(x for x in script.splitlines() if x.startswith("for c in "))
    # 이 컴퓨터의 파이썬을 못 찾은 것처럼 후보를 받아 둔 파이썬 하나로 줄인다(친구 맥처럼 3.11 이상이 없는 경우)
    script = script.replace(line, 'for c in "$HOME_DIR/python/bin/python3"; do')
    home = tmp_path / "home"
    env = _net_env({"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "TRACE_AGENT_HOME": str(home),
                    "TRACE_AGENT_SRC": _archive(tmp_path).as_uri()})
    result = _sh([], env, script)
    assert (home / "python" / "bin" / "python3").exists(), result.stdout + result.stderr
    assert "기기 정보를 읽는 중" in result.stdout, result.stdout + result.stderr


# [상황] 맥에 SSD 건강 도구 smartctl이 없다(맥 CI에서만 확인).
# [기대] 공식 설치 파일(dmg)에서 smartctl을 꺼내 설치 폴더 bin에 두고, 버전 7.4로 실행된다.
@pytest.mark.skipif(sys.platform != "darwin", reason="hdiutil·pkgutil은 macOS에만 있다")
def test_맥에_smartctl이_없으면_dmg에서_꺼내_bin에_둔다(tmp_path: Path) -> None:
    if any(Path(d, "smartctl").exists() for d in ("/usr/local/sbin", "/usr/local/bin", "/opt/homebrew/bin",
                                                  "/opt/homebrew/sbin")):
        pytest.skip("이 맥에는 이미 smartctl이 있다")
    # 에이전트 실행(수집·벤치마크) 직전에서 끊는다
    script = SCRIPT.read_text(encoding="utf-8").split("# 진단 JSON은")[0] + "exit 0\n"
    home = tmp_path / "home"
    env = _net_env({"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin:/usr/sbin:/sbin", "HOME": str(tmp_path),
                    "TRACE_AGENT_HOME": str(home), "TRACE_AGENT_SRC": _archive(tmp_path).as_uri()})
    result = _sh([], env, script)
    smartctl = home / "bin" / "smartctl"
    assert smartctl.exists(), result.stdout + result.stderr
    version = subprocess.run([str(smartctl), "--version"], check=False, capture_output=True, text=True)
    assert "smartctl 7.4" in version.stdout
