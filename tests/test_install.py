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


def _sh(args: list[str], env: dict[str, str], script: str | None = None) -> subprocess.CompletedProcess[str]:
    # curl | sh -s 처럼 스크립트를 표준 입력으로 준다
    text = SCRIPT.read_text(encoding="utf-8") if script is None else script
    return subprocess.run(["sh", "-s", *args], check=False, input=text,
                          capture_output=True,
                          text=True, env=env, timeout=300)


def test_6자리가_아닌_코드는_받기_전에_멈춘다(tmp_path: Path) -> None:
    result = _sh(["12ab"], {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)})
    assert result.returncode == 1
    assert "6자리" in result.stderr
    assert not (tmp_path / ".trace-agent").exists()


def _archive(tmp_path: Path) -> Path:
    archive = tmp_path / "agent.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(ROOT / "src", arcname="agent-develop/src")
        tar.add(ROOT / "pyproject.toml", arcname="agent-develop/pyproject.toml")
    return archive


@pytest.mark.skipif(sys.platform != "linux", reason="macOS CI에서는 실제 수집·벤치마크가 돌아 오래 걸린다")
def test_받은_소스를_풀어_에이전트를_부른다(tmp_path: Path) -> None:
    home = tmp_path / "home"
    env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(tmp_path),
           "TRACE_AGENT_HOME": str(home), "TRACE_AGENT_SRC": _archive(tmp_path).as_uri()}
    result = _sh([], env)
    assert (home / "src" / "trace_agent" / "__main__.py").exists()
    assert "기기 정보를 읽는 중" in result.stdout
    assert (home / "trace-diagnostics.json").exists()


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


def _net_env(env: dict[str, str]) -> dict[str, str]:
    for key in ("HTTPS_PROXY", "HTTP_PROXY", "https_proxy", "http_proxy", "NO_PROXY", "no_proxy", "PIP_CERT",
                "SSL_CERT_FILE", "CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE", "PIP_INDEX_URL"):
        if key in os.environ:
            env[key] = os.environ[key]
    return env


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
